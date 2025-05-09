import json
import traceback
import time
import uuid
from datetime import datetime
import socket
import os
import sys
import grpc
import threading
import random
import argparse
import heapq
from concurrent import futures
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Dict, Any
from order_executor_integration import OrderExecutorService

DEFAULT_HEARTBEAT_INTERVAL = 0.5  # seconds
MIN_ELECTION_TIMEOUT = 1.5  # seconds
MAX_ELECTION_TIMEOUT = 3.0  # seconds
DEFAULT_PORT = 50051
DEFAULT_MAX_WORKERS = 10
JOB_PROCESSING_INTERVAL = 2.0
MAX_JOBS_PARALLEL = 5

# proto
FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")

PROTO_DIR = os.path.abspath(os.path.join(FILE, "../../../utils/pb/order_executor"))

sys.path.insert(0, PROTO_DIR)

# Import protobuf modules
try:
    import raft_pb2
    import raft_pb2_grpc
except ImportError as e:
    print(f"Failed to import protobuf modules: {e}")
    print(f"Make sure protobuf definitions are at: {PROTO_DIR}")
    sys.exit(1)


class NodeState(Enum):
    """States of a Raft node."""

    FOLLOWER = auto()
    CANDIDATE = auto()
    LEADER = auto()

    def __str__(self):
        return self.name.lower()


@dataclass
class LogEntry:
    """Represents a log entry in the Raft algorithm."""

    term: int
    command: Any
    index: int
    priority: int = 0  # higher the more priority

    # For proper comparison in heapq
    def __lt__(self, other):
        # Higher priority comes first
        return self.priority > other.priority


@dataclass
class JobQueue:
    """Priority queue for jobs with thread safety."""

    _queue: List[LogEntry] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def enqueue(self, entry: LogEntry) -> None:
        """Add a job to the priority queue."""
        with self._lock:
            heapq.heappush(self._queue, entry)

    def dequeue(self) -> Optional[LogEntry]:
        """Remove and return the highest priority job."""
        with self._lock:
            if not self._queue:
                return None
            return heapq.heappop(self._queue)

    def peek(self) -> Optional[LogEntry]:
        """View the highest priority job without removing it."""
        with self._lock:
            if not self._queue:
                return None
            return self._queue[0]

    def is_empty(self) -> bool:
        """Check if the queue is empty."""
        with self._lock:
            return len(self._queue) == 0

    def size(self) -> int:
        """Get the number of jobs in the queue."""
        with self._lock:
            return len(self._queue)


class RaftNode(raft_pb2_grpc.RaftServicer):
    """Implementation of a node in the Raft consensus algorithm."""

    def __init__(self, node_id: str, peers: List[str], port: int = DEFAULT_PORT):
        """
        Initialize a Raft node.

        Args:
            node_id: Unique identifier for this node
            peers: List of peer addresses in format "host:port"
            port: Port on which this node listens
        """
        self.node_id = node_id
        self.peers = peers
        self.port = port
        self.address = f"[::]:{port}"

        # Multiple locks for different concerns
        self._state_lock = threading.RLock()  # For node state
        self._term_lock = threading.RLock()  # For term and voting
        self._log_lock = threading.RLock()  # For log entries
        self._leader_lock = threading.RLock()  # For leader state
        self._timer_lock = threading.RLock()  # For election timers

        # State to persist
        self.current_term = 0
        self.voted_for = None
        self.log = []  # log entries

        # On-the-fly state
        self.state = NodeState.FOLLOWER
        self.leader_id = None
        self.commit_index = 0
        self.last_applied = 0

        # Leader state
        self.next_index = {}  # Dict[peer_id, next_log_index]
        self.match_index = {}  # Dict[peer_id, highest_replicated_log_index]

        # Job queue for processing
        self.job_queue = JobQueue()

        # Threads and timers
        self._server = None
        self._election_timer = None
        self._heartbeat_timer = None
        self._job_processor_timer = None
        self._shutdown_event = threading.Event()

        # Track timing information
        self._last_heartbeat_time = time.time()
        self._last_timer_reset = time.time()

        # Track election state
        self._election_in_progress = False

        # Debug flag for log verbosity
        self._debug = os.environ.get("DEBUG", "false").lower() == "true"

        # Initially wait a bit before starting elections
        self._initial_timeout = True

        print(f"Node {self.node_id} initialized with peers: {self.peers}")

    def get_current_term(self):
        """Get current term safely."""
        with self._term_lock:
            return self.current_term

    def set_current_term(self, term):
        """Set current term safely."""
        with self._term_lock:
            self.current_term = term

    def get_voted_for(self):
        """Get voted_for safely."""
        with self._term_lock:
            return self.voted_for

    def set_voted_for(self, candidate_id):
        """Set voted_for safely."""
        with self._term_lock:
            self.voted_for = candidate_id

    def get_node_state(self):
        """Get node state safely."""
        with self._state_lock:
            return self.state

    def set_node_state(self, state):
        """Set node state safely."""
        with self._state_lock:
            self.state = state

    def is_election_in_progress(self):
        """Check if election is in progress safely."""
        with self._state_lock:
            return self._election_in_progress

    def set_election_in_progress(self, in_progress):
        """Set election in progress safely."""
        with self._state_lock:
            self._election_in_progress = in_progress

    def get_leader_id(self):
        """Get leader ID safely."""
        with self._leader_lock:
            return self.leader_id

    def set_leader_id(self, leader_id):
        """Set leader ID safely."""
        with self._leader_lock:
            self.leader_id = leader_id

    def get_last_log_info(self):
        """Get last log index and term safely."""
        with self._log_lock:
            last_log_index = len(self.log) - 1 if self.log else -1
            last_log_term = self.log[last_log_index].term if last_log_index >= 0 else 0
            return last_log_index, last_log_term

    def _get_random_election_timeout(self) -> float:
        """Generate a random election timeout."""
        # Add more randomness based on node ID to help break ties
        node_num = int(self.node_id.replace("node", ""))
        base_timeout = random.uniform(MIN_ELECTION_TIMEOUT, MAX_ELECTION_TIMEOUT)

        # Add slight variation based on node ID
        variation = (node_num % 5) * 0.1

        # During initial startup, use longer timeouts to let the system stabilize
        if self._initial_timeout:
            self._initial_timeout = False
            return base_timeout + variation + random.uniform(5, 10)

        return base_timeout + variation

    def _reset_election_timeout(self) -> None:
        """Reset the election timeout timer."""
        now = time.time()

        # Skip frequent resets to prevent timer thrashing
        with self._timer_lock:
            if self._election_timer and (now - self._last_timer_reset < 1.0):
                return

            # Check if we're a leader - leaders don't need election timers
            if self.get_node_state() == NodeState.LEADER:
                if self._election_timer:
                    self._election_timer.cancel()
                    self._election_timer = None
                return

            # Cancel existing timer
            if self._election_timer:
                self._election_timer.cancel()
                self._election_timer = None

            # Only set new timer if we're not shutting down
            if not self._shutdown_event.is_set():
                timeout = self._get_random_election_timeout()
                self._election_timer = threading.Timer(timeout, self._start_election)
                self._election_timer.daemon = True
                self._election_timer.start()

                print(
                    f"Node {self.node_id} reset election timer with timeout {timeout:.2f}s"
                )
                self._last_timer_reset = now

    def _start_election(self) -> None:
        """Start an election to become the leader."""
        # Quick check if we're already a leader or shutting down
        if self.get_node_state() == NodeState.LEADER or self._shutdown_event.is_set():
            return

        # Check and set election in progress
        with self._state_lock:
            if self._election_in_progress:
                return  # Skip if already electing
            self._election_in_progress = True

        # Update term and state
        with self._term_lock:
            self.current_term += 1
            self.voted_for = self.node_id
            term_for_vote = self.current_term

        # Set candidate state
        with self._state_lock:
            old_state = self.state
            self.state = NodeState.CANDIDATE

        # Log election start
        print(f"Node {self.node_id} starting election for term {term_for_vote}")

        # Get last log index/term
        last_log_index, last_log_term = self.get_last_log_info()

        # Use our node ID
        my_node_id = self.node_id

        # Create a counter for votes that can be updated by threads
        vote_counter = {"total": 1}  # Start with our own vote
        vote_lock = threading.Lock()

        # Create a tracking object for checking when we're done
        vote_tracking = {
            "total_responses": 0,
            "needed_responses": len(self.peers),
            "term": term_for_vote,
        }

        def vote_callback(peer, granted, term):
            with vote_lock:
                # Update votes if the vote was granted and still in same term
                if granted and term == vote_tracking["term"]:
                    vote_counter["total"] += 1

                # Track that we got a response
                vote_tracking["total_responses"] += 1

                # Check if election is complete (all votes in or majority reached)
                total_votes = vote_counter["total"]
                needed_for_majority = (len(self.peers) + 1) // 2 + 1

                if (
                    total_votes >= needed_for_majority
                    or vote_tracking["total_responses"]
                    >= vote_tracking["needed_responses"]
                ):
                    # Handle election completion
                    self._finish_election(total_votes, term_for_vote)

        # Launch separate threads for each peer to request votes
        for peer in self.peers:
            thread = threading.Thread(
                target=self._request_vote_thread,
                args=(
                    peer,
                    last_log_index,
                    last_log_term,
                    term_for_vote,
                    my_node_id,
                    vote_callback,
                ),
            )
            thread.daemon = True
            thread.start()

        # Set a timeout for election completion
        def election_timeout():
            with vote_lock:
                if vote_tracking["total_responses"] < vote_tracking["needed_responses"]:
                    # Election timed out without all responses
                    self._finish_election(vote_counter["total"], term_for_vote)

        # Set a slightly longer timeout than our RPC calls
        election_timer = threading.Timer(1.5, election_timeout)
        election_timer.daemon = True
        election_timer.start()

    def _finish_election(self, votes_received, election_term):
        """Finalize an election based on vote results."""
        # Check if we should process this election result
        current_state = self.get_node_state()
        current_term = self.get_current_term()

        if current_state != NodeState.CANDIDATE or current_term != election_term:
            # State has changed, ignore results
            print(
                f"Ignoring election results: state={current_state}, term={current_term} vs election_term={election_term}"
            )
            return

        # Reset election flag
        self.set_election_in_progress(False)

        print(
            f"Node {self.node_id} received {votes_received} votes out of {len(self.peers) + 1}"
        )

        # Check if we have majority
        needed_for_majority = (len(self.peers) + 1) // 2 + 1
        if votes_received >= needed_for_majority:
            print(
                f"WON ELECTION with {votes_received} votes (needed {needed_for_majority})"
            )
            self._become_leader()
        else:
            # Election unsuccessful, become follower again
            self.set_node_state(NodeState.FOLLOWER)
            self.set_voted_for(None)
            self._reset_election_timeout()
            print(f"Node {self.node_id} election unsuccessful, becoming follower")

    def _request_vote_thread(
        self, peer, last_log_index, last_log_term, term, candidate_id, callback
    ):
        """Thread function to request vote from a single peer."""
        try:
            print(f"Requesting vote from {peer} for term {term}")
            granted, response_term = self._request_vote_from_peer(
                peer, last_log_index, last_log_term, term, candidate_id
            )

            # Check if we need to revert to follower due to higher term
            if response_term > term:
                with self._term_lock:
                    if response_term > self.current_term:
                        self.current_term = response_term
                        # Become follower if not already
                        if self.get_node_state() != NodeState.FOLLOWER:
                            self.set_node_state(NodeState.FOLLOWER)
                            self.set_voted_for(None)
                            self.set_election_in_progress(False)
                            self._reset_election_timeout()
                            print(
                                f"Node {self.node_id} reverting to follower due to higher term {response_term}"
                            )

            # Call the callback with the results
            callback(peer, granted, term)

        except Exception as e:
            print(f"Error requesting vote from {peer}: {e}")
            # Still need to call callback to record response
            callback(peer, False, term)

    def _request_vote_from_peer(
        self, peer, last_log_index, last_log_term, term, candidate_id
    ):
        """
        Request vote from a single peer.

        Args:
            peer: Peer address
            last_log_index: Index of candidate's last log entry
            last_log_term: Term of candidate's last log entry
            term: Current term to use in request
            candidate_id: ID of the candidate node

        Returns:
            Tuple of (vote_granted, term)
        """
        try:
            with grpc.insecure_channel(peer) as channel:
                stub = raft_pb2_grpc.RaftStub(channel)

                request = raft_pb2.RequestVoteArgs(
                    term=term,
                    candidate_id=candidate_id,
                    last_log_index=last_log_index,
                    last_log_term=last_log_term,
                )

                # Set a timeout for the RPC
                response = stub.RequestVote(request, timeout=1.0)

                print(
                    f"Received vote response from {peer}: granted={response.vote_granted}, term={response.term}"
                )

                return response.vote_granted, response.term

        except grpc.RpcError as e:
            print(f"RPC failed when requesting vote from {peer}: {e.code()}")
            return False, term  # Return current term on failure

    def _become_leader(self) -> None:
        """Transition to leader state."""
        # First check if we're already a leader
        if self.get_node_state() == NodeState.LEADER:
            return

        # Update state
        self.set_node_state(NodeState.LEADER)
        self.set_leader_id(self.node_id)

        # Get term for logging
        current_term = self.get_current_term()

        print(f"Node {self.node_id} became leader for term {current_term}")

        # Initialize leader state
        last_log_index, _ = self.get_last_log_info()

        with self._leader_lock:
            for peer in self.peers:
                self.next_index[peer] = last_log_index + 1
                self.match_index[peer] = -1

        # Stop election timer
        with self._timer_lock:
            if self._election_timer:
                self._election_timer.cancel()
                self._election_timer = None

        # Start sending heartbeats immediately
        self._send_heartbeats()

        # Start job processing
        self._start_job_processor()

    def _become_follower(self, leader_id: Optional[str]) -> None:
        """Transition to follower state."""
        # First get current state
        was_leader = self.get_node_state() == NodeState.LEADER

        # Update state
        self.set_node_state(NodeState.FOLLOWER)
        self.set_election_in_progress(False)
        self.set_voted_for(None)
        self.set_leader_id(leader_id)

        print(f"Node {self.node_id} became follower, leader: {leader_id}")

        # If was leader, stop heartbeat timer and job processor
        if was_leader:
            if self._heartbeat_timer:
                self._heartbeat_timer.cancel()
                self._heartbeat_timer = None

            if self._job_processor_timer:
                self._job_processor_timer.cancel()
                self._job_processor_timer = None

        # Reset election timer
        self._reset_election_timeout()

    def _send_heartbeats(self) -> None:
        """Send heartbeats to all peers to maintain leadership."""
        # Check if we should continue
        if self._shutdown_event.is_set() or self.get_node_state() != NodeState.LEADER:
            return

        # Get snapshot of current state for consistent heartbeats
        current_term = self.get_current_term()
        leader_id = self.node_id

        # Send heartbeats in parallel
        for peer in self.peers:
            threading.Thread(
                target=self._send_heartbeat_to_peer,
                args=(peer, current_term, leader_id),
                daemon=True,
            ).start()

        # Schedule next heartbeat
        if not self._shutdown_event.is_set():
            self._heartbeat_timer = threading.Timer(
                DEFAULT_HEARTBEAT_INTERVAL, self._send_heartbeats
            )
            self._heartbeat_timer.daemon = True
            self._heartbeat_timer.start()

    def _send_heartbeat_to_peer(self, peer, term, leader_id):
        """Send a heartbeat to a specific peer."""
        try:
            # heartbeat
            request = raft_pb2.AppendEntriesArgs(
                term=term,
                leader_id=leader_id,
                prev_log_index=-1,  # For heartbeat
                prev_log_term=0,
                entries=[],
                leader_commit=0,
            )

            with grpc.insecure_channel(peer) as channel:
                stub = raft_pb2_grpc.RaftStub(channel)
                # timeout for heartbeat
                response = stub.AppendEntries(request, timeout=0.3)

                # Handle higher term
                if response.term > term:
                    with self._term_lock:
                        if response.term > self.current_term:
                            self.current_term = response.term
                            # Only become follower if we're still a leader
                            if self.get_node_state() == NodeState.LEADER:
                                self._become_follower(None)

        except grpc.RpcError as e:
            # Don't print every heartbeat error to reduce noise
            if str(e.code()) != "StatusCode.DEADLINE_EXCEEDED":
                print(f"Heartbeat to {peer} failed: {e.code()}")

    def _send_append_entries(self, peer: str) -> None:
        """
        Send AppendEntries RPC to a peer.

        Args:
            peer: Peer address
        """
        # Check if we're still a leader
        if self.get_node_state() != NodeState.LEADER:
            return

        # Get consistent state for the request
        current_term = self.get_current_term()
        leader_id = self.node_id

        # Get peer's next index and entries to send
        with self._leader_lock:
            if peer not in self.next_index:
                return

            next_idx = self.next_index[peer]
            commit_index = self.commit_index

        # Get log information
        with self._log_lock:
            prev_log_index = next_idx - 1
            prev_log_term = 0

            # Get previous log term if available
            if prev_log_index >= 0 and prev_log_index < len(self.log):
                prev_log_term = self.log[prev_log_index].term

            # Prepare entries to send
            entries = []
            if next_idx < len(self.log):
                entries = self.log[next_idx:]

        # Create request
        request = raft_pb2.AppendEntriesArgs(
            term=current_term,
            leader_id=leader_id,
            prev_log_index=prev_log_index,
            prev_log_term=prev_log_term,
            entries=[],  # In a full implementation, serialize LogEntry objects here
            leader_commit=commit_index,
        )

        # Send RPC
        try:
            with grpc.insecure_channel(peer) as channel:
                stub = raft_pb2_grpc.RaftStub(channel)
                response = stub.AppendEntries(request, timeout=1.0)

                # Only process if we're still a leader
                if self.get_node_state() != NodeState.LEADER:
                    return

                # Check for higher term
                if response.term > current_term:
                    with self._term_lock:
                        if response.term > self.current_term:
                            self.current_term = response.term
                            self._become_follower(None)
                    return

                # Update leader state on success
                if response.success:
                    with self._leader_lock:
                        # Update match index and next index
                        self.match_index[peer] = prev_log_index + len(entries)
                        self.next_index[peer] = self.match_index[peer] + 1
                else:
                    # Decrement next index on failure
                    with self._leader_lock:
                        self.next_index[peer] = max(0, prev_log_index)

        except grpc.RpcError as e:
            print(f"RPC failed when sending AppendEntries to {peer}: {e.code()}")

    def _replicate_log_entries(self) -> None:
        """Replicate log entries to followers."""
        if self.get_node_state() != NodeState.LEADER:
            return

        for peer in self.peers:
            try:
                self._send_append_entries(peer)
            except Exception as e:
                print(f"Failed to replicate log to {peer}: {e}")

    def _start_job_processor(self) -> None:
        """Start the job processing timer."""
        if self._shutdown_event.is_set() or self.get_node_state() != NodeState.LEADER:
            return

        # process pending jobs
        self._process_jobs()

        # schedule next job processing
        if not self._shutdown_event.is_set():
            self._job_processor_timer = threading.Timer(
                JOB_PROCESSING_INTERVAL, self._start_job_processor
            )
            self._job_processor_timer.daemon = True
            self._job_processor_timer.start()

    def _process_jobs(self) -> None:
        """Process jobs from the queue."""
        if self.get_node_state() != NodeState.LEADER:
            return

        # 5  jobs at a time
        jobs_processed = 0
        while not self.job_queue.is_empty() and jobs_processed < MAX_JOBS_PARALLEL:
            job = self.job_queue.dequeue()
            if job:
                try:
                    order_executor = OrderExecutorService.get_instance()

                    # order execution
                    job_id = job.command.get("order_id", str(uuid.uuid4()))
                    payload = job.command

                    print(f"Processing job: {job_id}")
                    result = order_executor.execute_order(job_id, payload)

                    # Log the result
                    if result.get("success", False):
                        print(f"Job {job_id} executed successfully")
                    else:
                        print(
                            f"Job {job_id} execution failed: {result.get('error', 'Unknown error')}"
                        )

                    jobs_processed += 1
                except Exception as e:
                    print(f"Error processing job: {e}")
                    # If processing fails, consider re-queuing with lower priority
                    job.priority -= 10
                    self.job_queue.enqueue(job)

    # gRPC service methods
    def RequestVote(self, request, context):
        """
        Process RequestVote RPC.

        Args:
            request: RequestVoteArgs message
            context: gRPC context

        Returns:
            RequestVoteResult message
        """
        print(
            f"Received vote request from {request.candidate_id} for term {request.term}"
        )

        with self._term_lock:
            # If term is outdated, reject
            if request.term < self.current_term:
                print(
                    f"Rejecting vote: term {request.term} < current term {self.current_term}"
                )
                return raft_pb2.RequestVoteResult(
                    term=self.current_term, vote_granted=False
                )

            # If term is newer, update and become follower
            if request.term > self.current_term:
                print(f"Newer term detected: {request.term} > {self.current_term}")
                self.current_term = request.term
                # Will release term_lock before calling _become_follower

            # Only vote if we haven't voted yet in this term or already voted for this candidate
            vote_granted = False
            if self.voted_for is None or self.voted_for == request.candidate_id:
                # Check if candidate's log is at least as up-to-date as ours
                last_log_index, last_log_term = self.get_last_log_info()

                log_ok = request.last_log_term > last_log_term or (
                    request.last_log_term == last_log_term
                    and request.last_log_index >= last_log_index
                )

                if log_ok:
                    vote_granted = True
                    self.voted_for = request.candidate_id
                    print(
                        f"Voting YES for {request.candidate_id} in term {request.term}"
                    )
                else:
                    print(f"Rejecting vote: candidate log not up-to-date")
            else:
                print(
                    f"Rejecting vote: already voted for {self.voted_for} in term {request.term}"
                )

            # Get current term for response
            response_term = self.current_term

        # Take actions outside of the term lock
        if request.term > response_term:
            self._become_follower(None)

        # Reset election timeout if vote granted
        if vote_granted:
            self._reset_election_timeout()

        return raft_pb2.RequestVoteResult(term=response_term, vote_granted=vote_granted)

    def AppendEntries(self, request, context):
        """
        Process AppendEntries RPC.

        Args:
            request: AppendEntriesArgs message
            context: gRPC context

        Returns:
            AppendEntriesResult message
        """
        # Log heartbeat reception
        print(
            f"Received AppendEntries from {request.leader_id} for term {request.term}"
        )

        with self._term_lock:
            # If term is outdated, reject
            if request.term < self.current_term:
                print(
                    f"Rejecting AppendEntries: term {request.term} < {self.current_term}"
                )
                return raft_pb2.AppendEntriesResult(
                    term=self.current_term, success=False
                )

            # Store current term for response
            current_term = self.current_term

            # Update term if newer
            if request.term > self.current_term:
                self.current_term = request.term

        # Reset election timeout - valid heartbeat
        self._reset_election_timeout()

        # Update leadership information
        current_state = self.get_node_state()
        if request.term >= current_term and (
            current_state != NodeState.FOLLOWER or current_state == NodeState.CANDIDATE
        ):
            print(f"Following leader {request.leader_id} for term {request.term}")
            self._become_follower(request.leader_id)
        elif current_state == NodeState.FOLLOWER:
            # Just update leader ID
            self.set_leader_id(request.leader_id)
            print(f"Updated leader to {request.leader_id} for term {request.term}")

        # Return success
        return raft_pb2.AppendEntriesResult(term=self.get_current_term(), success=True)

    def _calculate_priority(self, order: Dict[str, Any]) -> float:
        """Calculate priority score based on order attributes."""
        # Higher quantity = higher priority
        quantity_weight = order["amount"] * 0.4

        # Higher value = higher priority
        price_weight = order["price"] * 0.4

        # Older orders = higher priority (negative time decay)
        time_elapsed = (
            datetime.now() - datetime.fromisoformat(order["order_date"])
        ).seconds
        time_weight = -time_elapsed * 0.2

        return quantity_weight + price_weight + time_weight

    def SubmitJob(self, request, context):
        """
        Handle incoming order with priority calculation.

        Args:
            request: JobRequest with job_id, payload, and optional priority
            context: gRPC context

        Returns:
            JobResponse with success status and leader_id if needed for redirection
        """
        try:
            # Parse the payload
            order = json.loads(request.payload)
            order["order_id"] = request.job_id

            # Use provided priority or calculate if not provided
            priority = (
                request.priority
                if request.priority > 0
                else int(self._calculate_priority(order))
            )

            # Check if we're the leader
            if self.get_node_state() != NodeState.LEADER:
                leader_id = self.get_leader_id() or ""
                return raft_pb2.JobResponse(success=False, leader_id=leader_id)

            # Get term for log entry
            current_term = self.get_current_term()

            # Create and add log entry
            with self._log_lock:
                entry = LogEntry(
                    term=current_term,
                    command=order,
                    index=len(self.log),
                    # priority=priority,
                )

                # Add to log
                self.log.append(entry)

            # Add to priority queue for processing
            self.job_queue.enqueue(entry)

            # Replicate to followers
            self._replicate_log_entries()

            print(f"Job submitted with priority {priority}: {order}")

            return raft_pb2.JobResponse(success=True, leader_id=self.node_id)

        except Exception as e:
            traceback.print_exc()

            print(f"Error submitting job: {e}")
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(str(e))
            return raft_pb2.JobResponse(success=False)

    def GetLeader(self, request, context):
        """
        Return the current leader ID.

        Args:
            request: Empty message
            context: gRPC context

        Returns:
            LeaderResponse with the current leader's ID
        """
        leader = self.get_leader_id()
        if self.get_node_state() == NodeState.LEADER:
            leader = self.node_id

        return raft_pb2.LeaderResponse(leader_id=leader or "")

    def start(self) -> None:
        """Start the Raft node server."""
        self._server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=DEFAULT_MAX_WORKERS)
        )
        raft_pb2_grpc.add_RaftServicer_to_server(self, self._server)
        self._server.add_insecure_port(self.address)
        self._server.start()

        print(f"Node {self.node_id} started on {self.address}")

        # Reset election timeout to start participating in the cluster
        self._reset_election_timeout()

    def stop(self) -> None:
        """Stop the Raft node server gracefully."""
        print(f"Stopping node {self.node_id}")

        # Signal all threads to stop
        self._shutdown_event.set()

        # Cancel timers
        with self._timer_lock:
            if self._election_timer:
                self._election_timer.cancel()

        if self._heartbeat_timer:
            self._heartbeat_timer.cancel()

        if self._job_processor_timer:
            self._job_processor_timer.cancel()

        # Stop server with grace period
        if self._server:
            self._server.stop(grace=5)
            print(f"Node {self.node_id} stopped")

    def wait_for_termination(self) -> None:
        """Wait for the server to terminate."""
        if self._server:
            self._server.wait_for_termination()


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Raft Consensus Node")
    parser.add_argument("node_id", help="Unique identifier for this node")
    parser.add_argument(
        "peers", help="Comma-separated list of peer addresses (host:port)"
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="Port to listen on"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set logging level",
    )
    return parser.parse_args()


def discover_peers():
    """Discover other Raft nodes in the network."""
    # Check if peers are explicitly provided in environment
    peers_env = os.environ.get("PEERS", "")
    if peers_env:
        print(f"Using peers from environment: {peers_env}")
        # Remove self from peers list
        hostname = socket.gethostname()
        node_id = os.environ.get("NODE_ID", hostname)
        peers = []
        for peer in peers_env.split(","):
            # Skip peers that match our own node ID
            peer_name = peer.split(":")[0]
            if node_id not in peer_name and hostname not in peer_name:
                peers.append(peer)
        return peers

    # Fall back to auto-discovery if no peers provided
    peers = []
    node_count = int(os.environ.get("NODE_COUNT", "5"))

    # Get hostname to exclude self
    hostname = socket.gethostname()

    if os.environ.get("AUTO_DISCOVER", "false").lower() == "true":
        # wait for nodes to be available
        if os.environ.get("WAIT_FOR_NODES", "false").lower() == "true":
            print(f"Waiting for {node_count} nodes to be available...")
            time.sleep(random.uniform(1, 2))  # Add randomized startup delay

        # check for the other nodes
        for i in range(1, node_count + 1):
            peer_hostname = f"raft-node{i}"
            if peer_hostname != hostname:  # Skip self
                peers.append(f"{peer_hostname}:50051")

    return peers


def serve():
    # Get node ID
    node_id = os.environ.get("NODE_ID", socket.gethostname())

    # Wait for DNS resolution and network stabilization
    startup_delay = random.uniform(2, 5)
    print(f"Node {node_id} waiting {startup_delay:.1f}s for network setup...")
    time.sleep(startup_delay)

    # Discover peers
    peers = discover_peers()
    print(f"Node {node_id} discovered peers: {peers}")

    # Create and start Raft node
    port = int(os.environ.get("PORT", "50051"))
    node = RaftNode(node_id, peers, port)

    try:
        node.start()
        node.wait_for_termination()
    except KeyboardInterrupt:
        node.stop()
    except Exception as e:
        print(f"Error running node: {e}")
        node.stop()
        sys.exit(1)


if __name__ == "__main__":
    print("Starting Raft node...")
    serve()
