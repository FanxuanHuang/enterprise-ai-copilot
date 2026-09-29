import logging

from app.services.knowledge_service import knowledge_service


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    chunk_count = knowledge_service.build_index()
    print(f"Knowledge index ready with {chunk_count} chunks.")


if __name__ == "__main__":
    main()
