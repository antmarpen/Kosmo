FROM python:3.14-slim
RUN pip install --no-cache-dir requests pydantic && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox
COPY worker/script_runner.py /opt/kosmo/script_runner.py
COPY worker/validation_runner.py /opt/kosmo/validation_runner.py
WORKDIR /workspace
USER 10001:10001
ENTRYPOINT ["python"]
