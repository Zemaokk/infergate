import asyncio
import logging
from threading import Thread

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)
EXPORT_TIMEOUT_SECONDS = 2.0
SHUTDOWN_WAIT_SECONDS = 5.0


def configure_trace_export(provider: TracerProvider, endpoint: str) -> None:
    """Enable bounded background batching for one app-owned provider."""
    exporter = OTLPSpanExporter(endpoint=endpoint, timeout=EXPORT_TIMEOUT_SECONDS)
    try:
        processor = BatchSpanProcessor(
            exporter,
            max_queue_size=2048,
            max_export_batch_size=256,
            schedule_delay_millis=1000,
            export_timeout_millis=int(EXPORT_TIMEOUT_SECONDS * 1000),
        )
    except Exception:
        exporter.shutdown()
        raise
    provider.add_span_processor(processor)


async def shutdown_trace_provider(
    provider: TracerProvider, timeout_seconds: float = SHUTDOWN_WAIT_SECONDS
) -> bool:
    """Bound lifecycle waiting, not the SDK thread or delivery guarantee."""
    loop = asyncio.get_running_loop()
    finished = loop.create_future()

    def deliver_result(success: bool) -> None:
        if not finished.done():
            finished.set_result(success)

    def shutdown() -> None:
        try:
            # SDK shutdown drains its batch queue; force_flush has no reliable
            # overall time bound in this version, so do not call it first.
            provider.shutdown()
            success = True
        except Exception:  # noqa: BLE001
            success = False
        try:
            loop.call_soon_threadsafe(deliver_result, success)
        except RuntimeError:
            # The event loop may already be closed after the waiting deadline.
            pass

    # A timed-out SDK shutdown may finish later, but must not hold process exit.
    Thread(target=shutdown, name="infergate-trace-shutdown", daemon=True).start()
    try:
        success = await asyncio.wait_for(finished, timeout_seconds)
    except TimeoutError:
        success = False
    if not success:
        try:
            logger.warning("Trace shutdown failed or exceeded the waiting budget")
        except Exception:  # noqa: BLE001
            pass
    return success
