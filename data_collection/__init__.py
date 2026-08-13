"""Offline corpus pipeline: fetch -> parse -> enrich -> chunk -> build_index.

Every stage runs on the maintainer's machine with `DEV_LLM_API_KEY`; none of it
runs while a user is asking a question (constitution Principle II).
"""
