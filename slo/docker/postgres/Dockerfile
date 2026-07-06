ARG PG_MAJOR=16
FROM pgvector/pgvector:pg${PG_MAJOR}

RUN apt-get update -y && apt-get install -y \
    curl \
    build-essential \
    ca-certificates \
    libssl-dev \
    libffi-dev \
    procps \
    git \
    telnet \
    net-tools

ADD ./postgres/init.sh /docker-entrypoint-initdb.d/init.sh
RUN chown postgres:postgres /docker-entrypoint-initdb.d/init.sh

EXPOSE 5432
