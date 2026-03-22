from app.db.base import (
    build_async_engine_kwargs,
    build_sync_database_url,
    build_sync_engine_kwargs,
)


def test_build_sync_database_url_handles_sqlite_async_url() -> None:
    assert build_sync_database_url("sqlite+aiosqlite:///./future_of_video.db") == "sqlite:///./future_of_video.db"


def test_build_sync_database_url_handles_mysql_async_url() -> None:
    assert (
        build_sync_database_url("mysql+aiomysql://user:pass@127.0.0.1:3306/future_of_video")
        == "mysql+pymysql://user:pass@127.0.0.1:3306/future_of_video"
    )


def test_sqlite_engine_kwargs_skip_mysql_pool_settings() -> None:
    sync_kwargs = build_sync_engine_kwargs("sqlite+aiosqlite:///./future_of_video.db")
    async_kwargs = build_async_engine_kwargs("sqlite+aiosqlite:///./future_of_video.db")

    assert sync_kwargs["connect_args"]["check_same_thread"] is False
    assert async_kwargs["connect_args"]["check_same_thread"] is False
    assert "pool_size" not in sync_kwargs
    assert "pool_size" not in async_kwargs
