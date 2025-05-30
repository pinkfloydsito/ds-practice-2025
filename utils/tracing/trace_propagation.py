"""
Handle trace propagation across gRPC services
"""

from opentelemetry import trace
from opentelemetry.propagate import inject, extract
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
import grpc


class TracingInterceptor(grpc.UnaryUnaryClientInterceptor):
    """Client interceptor to inject trace context into gRPC calls"""

    def intercept_unary_unary(self, continuation, client_call_details, request):
        # Create metadata carrier
        metadata = {}

        # Inject current trace context
        inject(metadata)

        # Add to gRPC metadata
        if client_call_details.metadata:
            new_metadata = list(client_call_details.metadata)
        else:
            new_metadata = []

        for key, value in metadata.items():
            new_metadata.append((key, value))

        # Create new call details with trace metadata
        new_details = client_call_details._replace(metadata=new_metadata)

        return continuation(new_details, request)


class TracingServerInterceptor(grpc.ServerInterceptor):
    """Server interceptor to extract trace context from gRPC calls"""

    def intercept_service(self, continuation, handler_call_details):
        # Extract metadata
        metadata_dict = {}
        if handler_call_details.invocation_metadata:
            for key, value in handler_call_details.invocation_metadata:
                metadata_dict[key] = value

        # Extract trace context
        context = extract(metadata_dict)

        # Run handler with extracted context
        with trace.use_context(context):
            return continuation(handler_call_details)
