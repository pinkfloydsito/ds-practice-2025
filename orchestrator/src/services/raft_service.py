import os
import json

from datetime import datetime
import random
import uuid
import grpc

from typing import List, Dict

from utils.grpc_config import GrpcConfig
from google.protobuf.json_format import MessageToDict

config = GrpcConfig()
FILE = __file__ if "__file__" in globals() else os.getenv("PYTHONFILE", "")
config.init_paths(FILE)
config.setup_paths()

import raft_pb2 as raft
import raft_pb2_grpc as raft_grpc

from bookstore_models import ServiceResult


class RaftService:
    """Client for the raft service."""

    def __init__(self, grpc_factory):
        self.grpc_factory = grpc_factory

    def submit_job(self, order_id: str, payload) -> ServiceResult:
        """Get book suggestions."""
        result = ServiceResult()
        try:
            stub = self.grpc_factory.get_stub(
                "order_executor",
                raft_grpc.RaftStub,
                secure=False,
            )

            request = raft.JobRequest(
                job_id=order_id,
                payload=json.dumps(payload),
                priority=0,  # this is calculated in the order executor
            )

            response = stub.SubmitJob(request)
            # debug print(response)

            if not response.success:
                print(f"Leader identified: {response.leader_id}")
                self.grpc_factory.update_leader(response.leader_id)

                return self.submit_job(order_id, payload)

            result.success = response.success
            return result
        except grpc.RpcError as e:
            print(f"gRPC error in submit_job: {e.code()}: {e.details()}")
            result.error = f"gRPC error: {e.code()}: {e.details()}"
            return result
