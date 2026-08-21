import psycopg

from core.config import settings


def main():
    try:
        conn = psycopg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            dbname=settings.postgres_db,
            user=settings.postgres_user,
            password=settings.postgres_password,
        )
    except psycopg.OperationalError as e:
        print("Connection failed (check Docker is up / credentials / host+port):")
        print(e)
        return

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            result = cur.fetchone()
            print("Connected. SELECT 1 ->", result)
    finally:
        conn.close()


if __name__ == "__main__":
    main()