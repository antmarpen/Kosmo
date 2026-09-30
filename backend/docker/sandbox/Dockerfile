FROM python:3.14-slim
RUN pip install --no-cache-dir requests pydantic && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox
WORKDIR /workspace
USER 10001:10001
ENTRYPOINT ["python"]
