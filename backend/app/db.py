from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Import all models so Base.metadata.create_all() picks them up
import app.models.user  # noqa: F401, E402
import app.models.org  # noqa: F401, E402
import app.models.team  # noqa: F401, E402
import app.models.rate_limit  # noqa: F401, E402
import app.models.user_settings  # noqa: F401, E402
import app.models.ingestion_data  # noqa: F401, E402
import app.models.context  # noqa: F401, E402
import app.models.revision  # noqa: F401, E402


async def get_session() -> AsyncSession:  # type: ignore[misc]
    async with async_session() as session:
        yield session
