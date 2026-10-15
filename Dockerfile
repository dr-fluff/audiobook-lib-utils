FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .

VOLUME ["/data"]
EXPOSE 8686
ENV AUDIOBOOK_LIB_DATABASE=/data/audiobook-library.sqlite3
ENTRYPOINT ["audiobook-lib"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8686"]
