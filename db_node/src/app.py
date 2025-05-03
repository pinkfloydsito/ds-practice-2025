import json
import time
import socket
import os
import sys
import grpc
import threading
import random
from concurrent import futures
from datetime import datetime
from enum import Enum, auto
from typing import Dict, Any, List, Optional, Tuple

# Constants
DEFAULT_PORT = 50052
DEFAULT_HEARTBEAT_INTERVAL = 1.0  # seconds
DEFAULT_MAX_WORKERS = 10
MIN_ELECTION_TIMEOUT = 1.5  # seconds
MAX_ELECTION_TIMEOUT = 3.0  # seconds

# Import protobuf modules - assuming similar path structure
FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
PROTO_DIR = os.path.abspath(os.path.join(FILE, "../../../utils/pb/database"))
sys.path.insert(0, PROTO_DIR)

try:
    import db_node_pb2
    import db_node_pb2_grpc
except ImportError as e:
    print(f"Failed to import database protobuf modules: {e}")
    print(f"Make sure protobuf definitions are at: {PROTO_DIR}")
    sys.exit(1)


class NodeRole(Enum):
    """Roles of a database node."""

    PRIMARY = auto()
    CANDIDATE = auto()
    REPLICA = auto()

    def __str__(self):
        return self.name.lower()


class DatabaseNode(db_node_pb2_grpc.DatabaseServicer):
    """Implementation of a node in the distributed database system with leader election."""

    def __init__(
        self,
        node_id: str,
        peers: List[str],
        role: NodeRole = NodeRole.REPLICA,
        port: int = DEFAULT_PORT,
    ):
        """
        Initialize a database node.

        Args:
            node_id: Unique identifier for this node
            peers: List of peer addresses in format "host:port"
            role: Initial role of this node (PRIMARY or REPLICA)
            port: Port on which this node listens
        """
        self.node_id = node_id
        self.peers = peers
        self.port = port
        self.address = f"[::]:{port}"
        self.role = role

        # Store data in memory
        self.data_store: Dict[str, Any] = {}

        # Version control for each key
        self.versions: Dict[str, int] = {}

        # Locks for thread safety
        self._data_lock = threading.RLock()
        self._role_lock = threading.RLock()
        self._replication_lock = threading.RLock()
        self._election_lock = threading.RLock()
        self._timer_lock = threading.RLock()

        # Primary node information
        self._primary_id = None
        self._primary_address = None

        # Server and shutdown control
        self._server = None
        self._shutdown_event = threading.Event()
        self._heartbeat_timer = None
        self._election_timer = None

        # Term and voting information (for leader election)
        self.current_term = 0
        self.voted_for = None
        self._last_heartbeat_time = time.time()
        self._election_in_progress = False

        # Operation log for replication
        self.operation_log = []
        self.last_replicated_index = 0

        # Add random delay to initial election timeout to avoid conflict
        self._initial_timeout = True

        print(
            f"Node {self.node_id} initialized with role {self.role} and peers: {self.peers}"
        )

    def get_role(self) -> NodeRole:
        """Get current role safely."""
        with self._role_lock:
            return self.role

    def set_role(self, role: NodeRole) -> None:
        """Set role safely."""
        with self._role_lock:
            old_role = self.role
            self.role = role
            if old_role != role:
                print(f"Node {self.node_id} changed role from {old_role} to {role}")

                # Take appropriate actions based on new role
                if role == NodeRole.PRIMARY:
                    self._start_heartbeats()
                    self._stop_election_timer()
                elif role == NodeRole.CANDIDATE:
                    # As candidate, we don't send heartbeats
                    self._stop_heartbeat_timer()
                else:  # REPLICA
                    # As replica, we reset election timer but don't send heartbeats
                    self._stop_heartbeat_timer()
                    self._reset_election_timeout()

    def get_primary_info(self) -> Tuple[Optional[str], Optional[str]]:
        """Get primary node information safely."""
        with self._role_lock:
            return self._primary_id, self._primary_address

    def set_primary_info(self, primary_id: str, primary_address: str) -> None:
        """Set primary node information safely."""
        with self._role_lock:
            self._primary_id = primary_id
            self._primary_address = primary_address
            print(f"Primary info updated: ID={primary_id}, Address={primary_address}")

    def get_current_term(self) -> int:
        """Get current term safely."""
        with self._election_lock:
            return self.current_term

    def set_current_term(self, term: int) -> None:
        """Set current term safely."""
        with self._election_lock:
            if term > self.current_term:
                self.current_term = term
                self.voted_for = None  # Reset vote on new term

    def get_voted_for(self) -> Optional[str]:
        """Get voted_for safely."""
        with self._election_lock:
            return self.voted_for

    def set_voted_for(self, candidate_id: Optional[str]) -> None:
        """Set voted_for safely."""
        with self._election_lock:
            self.voted_for = candidate_id

    def update_last_heartbeat(self) -> None:
        """Update the timestamp of the last received heartbeat."""
        with self._timer_lock:
            self._last_heartbeat_time = time.time()

    def _get_random_election_timeout(self) -> float:
        """Generate a random election timeout."""
        # Add more randomness based on node ID to help break ties
        node_num = int(self.node_id.replace("db-node", ""))
        base_timeout = random.uniform(MIN_ELECTION_TIMEOUT, MAX_ELECTION_TIMEOUT)

        # Add slight variation based on node ID
        variation = (node_num % 5) * 0.1

        # During initial startup, use longer timeouts to let the system stabilize
        if self._initial_timeout:
            self._initial_timeout = False
            return base_timeout + variation + random.uniform(2, 5)

        return base_timeout + variation

    def _reset_election_timeout(self) -> None:
        """Reset the election timeout timer."""
        # Skip if we're a primary
        if self.get_role() == NodeRole.PRIMARY:
            return

        with self._timer_lock:
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

    def _stop_election_timer(self) -> None:
        """Stop the election timer."""
        with self._timer_lock:
            if self._election_timer:
                self._election_timer.cancel()
                self._election_timer = None

    def _start_election(self) -> None:
        """Start an election to become the primary."""
        # Skip if shutting down or already a primary
        if self._shutdown_event.is_set() or self.get_role() == NodeRole.PRIMARY:
            return

        # Check and set election in progress
        with self._election_lock:
            if self._election_in_progress:
                return  # Skip if election already in progress

            self._election_in_progress = True
            self.current_term += 1
            self.voted_for = self.node_id  # Vote for ourselves
            election_term = self.current_term

        # Change to candidate role
        self.set_role(NodeRole.CANDIDATE)

        print(f"Node {self.node_id} starting election for term {election_term}")

        # Count votes (starting with our own vote)
        votes_received = 1
        votes_needed = len(self.peers) // 2 + 1  # Majority of nodes

        # Request votes from all peers
        for peer in self.peers:
            # Send vote requests in parallel
            threading.Thread(
                target=self._request_vote_from_peer,
                args=(peer, election_term, votes_received, votes_needed),
                daemon=True,
            ).start()

        # Set a timeout for the election
        election_timeout = threading.Timer(
            MAX_ELECTION_TIMEOUT, self._handle_election_timeout, args=(election_term,)
        )
        election_timeout.daemon = True
        election_timeout.start()

    def _request_vote_from_peer(
        self, peer: str, term: int, votes_received: int, votes_needed: int
    ) -> None:
        """Request vote from a peer."""
        try:
            # Create request
            request = db_node_pb2.VoteRequest(
                term=term,
                candidate_id=self.node_id,
                last_log_index=len(self.operation_log) - 1
                if self.operation_log
                else -1,
            )

            # Send request
            with grpc.insecure_channel(peer) as channel:
                stub = db_node_pb2_grpc.DatabaseStub(channel)
                response = stub.RequestVote(request, timeout=1.0)

                # Process response
                if response.vote_granted:
                    print(f"Received vote from {peer} for term {term}")

                    # Check if we're still a candidate in the same term
                    with self._election_lock:
                        if (
                            self.get_role() == NodeRole.CANDIDATE
                            and self.current_term == term
                            and self._election_in_progress
                        ):
                            # Increment votes and check if we have enough
                            nonlocal votes_received
                            votes_received += 1

                            if votes_received >= votes_needed:
                                # We won! Become primary
                                self._become_primary(term)
                else:
                    # If they responded with a higher term, update our term
                    if response.term > term:
                        self.set_current_term(response.term)
                        self.set_role(NodeRole.REPLICA)
                        self._election_in_progress = False
                        self._reset_election_timeout()

        except grpc.RpcError as e:
            print(f"Error requesting vote from {peer}: {e}")

    def _handle_election_timeout(self, election_term: int) -> None:
        """Handle election timeout."""
        with self._election_lock:
            # Only handle if we're still a candidate in this term
            if (
                self.get_role() == NodeRole.CANDIDATE
                and self.current_term == election_term
                and self._election_in_progress
            ):
                print(f"Election for term {election_term} timed out")

                # Reset election state
                self._election_in_progress = False

                # Become replica again and start a new election timer
                self.set_role(NodeRole.REPLICA)
                self._reset_election_timeout()

    def _become_primary(self, term: int) -> None:
        """Become the primary node."""
        with self._election_lock:
            # Only become primary if we're still a candidate in this term
            if self.get_role() != NodeRole.CANDIDATE or self.current_term != term:
                return

            # Update state
            self._election_in_progress = False

            # Update role to primary
            self.set_role(NodeRole.PRIMARY)
            self.set_primary_info(self.node_id, self.address)

            print(
                f"Node {self.node_id} won election for term {term} and became primary"
            )

            # send heartbeats to replicas
            self._start_heartbeats()

    def _start_heartbeats(self) -> None:
        """Send heartbeats to replicas to maintain leadership."""
        # Check if we should continue
        if self._shutdown_event.is_set() or self.get_role() != NodeRole.PRIMARY:
            return

        # Send heartbeats to replicas in parallel
        for peer in self.peers:
            threading.Thread(
                target=self._send_heartbeat_to_replica,
                args=(peer,),
                daemon=True,
            ).start()

        # Schedule next heartbeat
        if not self._shutdown_event.is_set():
            self._heartbeat_timer = threading.Timer(
                DEFAULT_HEARTBEAT_INTERVAL, self._start_heartbeats
            )
            self._heartbeat_timer.daemon = True
            self._heartbeat_timer.start()

    def _stop_heartbeat_timer(self) -> None:
        """Stop the heartbeat timer."""
        if self._heartbeat_timer:
            self._heartbeat_timer.cancel()
            self._heartbeat_timer = None

    def _send_heartbeat_to_replica(self, replica_address: str) -> None:
        """Send heartbeat and replication updates to a specific replica."""
        try:
            # Prepare updates to send
            with self._replication_lock:
                # Get operations that haven't been sent to this replica yet
                updates_to_send = self.operation_log[self.last_replicated_index :]

                # Create serialized updates
                serialized_updates = [json.dumps(op) for op in updates_to_send]

                # Create the request
                request = db_node_pb2.HeartbeatRequest(
                    primary_id=self.node_id,
                    term=self.current_term,
                    updates=serialized_updates,
                    last_index=self.last_replicated_index + len(updates_to_send) - 1,
                )

            # Send the heartbeat with updates
            with grpc.insecure_channel(replica_address) as channel:
                stub = db_node_pb2_grpc.DatabaseStub(channel)
                # Set a short timeout for heartbeats
                response = stub.Heartbeat(request, timeout=0.5)

                # Check for higher term
                if response.term > self.current_term:
                    self.set_current_term(response.term)
                    self.set_role(NodeRole.REPLICA)
                    return

                # Update replication state on success
                if response.success:
                    with self._replication_lock:
                        # Note: In a production system, we'd track replication state per replica
                        pass

        except grpc.RpcError as e:
            if str(e.code()) != "StatusCode.DEADLINE_EXCEEDED":
                print(f"Heartbeat to {replica_address} failed: {e}")

    def Heartbeat(self, request, context):
        """
        Handle heartbeat from primary with potential updates.

        Args:
            request: HeartbeatRequest with updates
            context: gRPC context

        Returns:
            HeartbeatResponse with success status
        """
        term = request.term
        primary_id = request.primary_id

        # Check term
        current_term = self.get_current_term()
        if term < current_term:
            return db_node_pb2.HeartbeatResponse(
                success=False, term=current_term, message="Outdated term"
            )

        # If higher term, update our term
        if term > current_term:
            self.set_current_term(term)

        # Reset election timeout and become replica if not already
        self.update_last_heartbeat()
        if self.get_role() != NodeRole.REPLICA:
            self.set_role(NodeRole.REPLICA)

        # Update primary info
        self.set_primary_info(primary_id, context.peer())

        # Reset election timer
        self._reset_election_timeout()

        # Apply any updates
        if request.updates:
            with self._data_lock:
                for update_json in request.updates:
                    try:
                        update = json.loads(update_json)
                        key = update.get("key")
                        value = update.get("value")
                        version = update.get("version", 0)

                        # Update the data and version
                        self.data_store[key] = value
                        self.versions[key] = version
                    except json.JSONDecodeError:
                        print(f"Error decoding update: {update_json}")
                        continue

                # Update last applied index
                self.last_replicated_index = request.last_index

        return db_node_pb2.HeartbeatResponse(success=True, term=self.current_term)

    def RequestVote(self, request, context):
        """
        Handle vote request from a candidate.

        Args:
            request: VoteRequest
            context: gRPC context

        Returns:
            VoteResponse
        """
        candidate_id = request.candidate_id
        term = request.term

        with self._election_lock:
            current_term = self.current_term

            # Reject if candidate's term is older
            if term < current_term:
                return db_node_pb2.VoteResponse(vote_granted=False, term=current_term)

            # If term is newer, update our term and reset our vote
            if term > current_term:
                self.current_term = term
                self.voted_for = None

            # Decide whether to grant vote
            if self.voted_for is None or self.voted_for == candidate_id:
                # We haven't voted yet in this term or already voted for this candidate

                # Check if candidate's log is at least as up-to-date as ours
                last_log_index = (
                    len(self.operation_log) - 1 if self.operation_log else -1
                )

                if request.last_log_index >= last_log_index:
                    # Grant vote
                    self.voted_for = candidate_id
                    print(
                        f"Node {self.node_id} voted for {candidate_id} in term {term}"
                    )

                    # Reset timer since we decided to follow this candidate
                    self.update_last_heartbeat()

                    return db_node_pb2.VoteResponse(
                        vote_granted=True, term=self.current_term
                    )

            # Deny vote
            return db_node_pb2.VoteResponse(vote_granted=False, term=self.current_term)

    def Read(self, request, context):
        """
        Read value for a key.

        Args:
            request: ReadRequest with key
            context: gRPC context

        Returns:
            ReadResponse with value and success status
        """
        key = request.key

        with self._data_lock:
            if key in self.data_store:
                value = self.data_store[key]
                version = self.versions.get(key, 0)
                return db_node_pb2.ReadResponse(
                    success=True, value=str(value), version=version
                )
            else:
                return db_node_pb2.ReadResponse(
                    success=False, message=f"Key '{key}' not found", version=0
                )

    def Write(self, request, context):
        """
        Write value for a key.

        Args:
            request: WriteRequest with key and value
            context: gRPC context

        Returns:
            WriteResponse with success status
        """
        # Check if this node is primary
        if self.get_role() != NodeRole.PRIMARY:
            # Redirect to primary
            primary_id, primary_address = self.get_primary_info()
            if primary_address:
                return db_node_pb2.WriteResponse(
                    success=False,
                    message=f"Not the primary node, please write to {primary_id}",
                    primary_id=primary_id,
                )
            else:
                return db_node_pb2.WriteResponse(
                    success=False, message="Not the primary node and primary unknown"
                )

        # Process write on primary
        key = request.key
        value = request.value

        try:
            value_obj = value
            if request.type == db_node_pb2.WriteRequest.ValueType.STRING:
                # Leave as string
                pass
            elif request.type == db_node_pb2.WriteRequest.ValueType.INT:
                value_obj = int(value)
            elif request.type == db_node_pb2.WriteRequest.ValueType.FLOAT:
                value_obj = float(value)
            elif request.type == db_node_pb2.WriteRequest.ValueType.JSON:
                value_obj = json.loads(value)

            with self._data_lock:
                # Update version
                current_version = self.versions.get(key, 0)
                new_version = current_version + 1

                # Update data store
                self.data_store[key] = value_obj
                self.versions[key] = new_version

                # Add to operation log for replication
                operation = {
                    "key": key,
                    "value": value_obj,
                    "version": new_version,
                    "timestamp": datetime.now().isoformat(),
                }
                self.operation_log.append(operation)

            return db_node_pb2.WriteResponse(success=True, version=new_version)

        except Exception as e:
            return db_node_pb2.WriteResponse(
                success=False, message=f"Error writing value: {str(e)}"
            )

    def DecrementStock(self, request, context):
        """
        Atomic decrement operation for stock.

        Args:
            request: DecrementRequest with key and amount
            context: gRPC context

        Returns:
            DecrementResponse with new value and success status
        """
        # Check if this node is primary
        if self.get_role() != NodeRole.PRIMARY:
            # Redirect to primary
            primary_id, primary_address = self.get_primary_info()
            if primary_address:
                return db_node_pb2.DecrementResponse(
                    success=False,
                    message=f"Not the primary node, please write to {primary_id}",
                    primary_id=primary_id,
                )
            else:
                return db_node_pb2.DecrementResponse(
                    success=False, message="Not the primary node and primary unknown"
                )

        key = request.key
        amount = request.amount

        with self._data_lock:
            if key not in self.data_store:
                return db_node_pb2.DecrementResponse(
                    success=False, message=f"Key '{key}' not found"
                )

            try:
                current_value = self.data_store[key]
                if not isinstance(current_value, (int, float)):
                    return db_node_pb2.DecrementResponse(
                        success=False, message=f"Value for key '{key}' is not a number"
                    )

                if current_value < amount:
                    return db_node_pb2.DecrementResponse(
                        success=False,
                        message=f"Insufficient stock ({current_value}) to decrement by {amount}",
                        current_value=current_value,
                    )

                # Update value
                new_value = current_value - amount

                # Update version
                current_version = self.versions.get(key, 0)
                new_version = current_version + 1

                # Update data store
                self.data_store[key] = new_value
                self.versions[key] = new_version

                # Add to operation log for replication
                operation = {
                    "key": key,
                    "value": new_value,
                    "version": new_version,
                    "timestamp": datetime.now().isoformat(),
                }
                self.operation_log.append(operation)

                return db_node_pb2.DecrementResponse(
                    success=True, new_value=new_value, version=new_version
                )

            except Exception as e:
                return db_node_pb2.DecrementResponse(
                    success=False, message=f"Error decrementing value: {str(e)}"
                )

    def GetStatus(self, request, context):
        """
        Get status of this database node.

        Args:
            request: Empty message
            context: gRPC context

        Returns:
            StatusResponse with node information
        """
        role = str(self.get_role())
        primary_id, _ = self.get_primary_info()

        with self._data_lock:
            record_count = len(self.data_store)

        return db_node_pb2.StatusResponse(
            node_id=self.node_id,
            role=role,
            primary_id=primary_id or "unknown",
            record_count=record_count,
            term=self.current_term,
        )

    def start(self) -> None:
        """Start the database node server."""
        self._server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=DEFAULT_MAX_WORKERS)
        )
        db_node_pb2_grpc.add_DatabaseServicer_to_server(self, self._server)
        self._server.add_insecure_port(self.address)
        self._server.start()

        print(f"Database node {self.node_id} started on {self.address}")

        # If primary, start sending heartbeats
        if self.get_role() == NodeRole.PRIMARY:
            self._start_heartbeats()
        else:
            # Start election timer for replicas
            self._reset_election_timeout()

    def stop(self) -> None:
        """Stop the database node server gracefully."""
        print(f"Stopping database node {self.node_id}")

        # Signal all threads to stop
        self._shutdown_event.set()

        # Cancel timers
        self._stop_heartbeat_timer()
        self._stop_election_timer()

        # Stop server with grace period
        if self._server:
            self._server.stop(grace=5)
            print(f"Database node {self.node_id} stopped")

    def wait_for_termination(self) -> None:
        """Wait for the server to terminate."""
        if self._server:
            self._server.wait_for_termination()


def discover_peers():
    """Discover other database nodes in the network."""
    # Check if peers are explicitly provided in environment
    peers_env = os.environ.get("DB_PEERS", "")
    if peers_env:
        print(f"Using database peers from environment: {peers_env}")
        # Remove self from peers list
        hostname = socket.gethostname()
        node_id = os.environ.get("DB_NODE_ID", hostname)
        peers = []
        for peer in peers_env.split(","):
            # Skip peers that match our own node ID
            peer_name = peer.split(":")[0]
            if node_id not in peer_name and hostname not in peer_name:
                peers.append(peer)
        return peers

    # Fall back to auto-discovery if no peers provided
    peers = []
    node_count = int(os.environ.get("DB_NODE_COUNT", "3"))

    # Get hostname to exclude self
    hostname = socket.gethostname()

    if os.environ.get("DB_AUTO_DISCOVER", "true").lower() == "true":
        # wait for nodes to be available
        if os.environ.get("DB_WAIT_FOR_NODES", "true").lower() == "true":
            print(f"Waiting for {node_count} database nodes to be available...")
            time.sleep(random.uniform(1, 2))  # Add randomized startup delay

        # check for the other nodes
        for i in range(1, node_count + 1):
            peer_hostname = f"db-node{i}"
            if peer_hostname != hostname:  # Skip self
                peers.append(f"{peer_hostname}:50052")

    return peers


def serve():
    # Get node ID
    node_id = os.environ.get("DB_NODE_ID", socket.gethostname())

    # Wait for DNS resolution and network stabilization
    startup_delay = random.uniform(2, 5)
    print(f"Database node {node_id} waiting {startup_delay:.1f}s for network setup...")
    time.sleep(startup_delay)

    # Discover peers
    peers = discover_peers()
    print(f"Database node {node_id} discovered peers: {peers}")

    # Determine initial node role based on environment or node ID
    role_env = os.environ.get("DB_ROLE", "").upper()
    if role_env == "PRIMARY":
        role = NodeRole.PRIMARY
    elif role_env == "REPLICA":
        role = NodeRole.REPLICA
    else:
        # Default: all nodes start as replicas and elect a leader
        role = NodeRole.REPLICA

    # Create and start database node
    port = int(os.environ.get("DB_PORT", "50052"))
    node = DatabaseNode(node_id, peers, role, port)

    try:
        node.start()
        node.wait_for_termination()
    except KeyboardInterrupt:
        node.stop()
    except Exception as e:
        print(f"Error running database node: {e}")
        node.stop()
        sys.exit(1)


if __name__ == "__main__":
    print("Starting database node...")
    serve()
