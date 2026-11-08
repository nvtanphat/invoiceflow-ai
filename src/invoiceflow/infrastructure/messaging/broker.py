import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker
from invoiceflow.config import get_settings


def setup_broker() -> dramatiq.Broker:
    settings = get_settings()
    try:
        broker = RedisBroker(url=settings.REDIS_URL)
        broker.ping()
        dramatiq.set_broker(broker)
        return broker
    except Exception:
        broker = StubBroker()
        dramatiq.set_broker(broker)
        return broker
