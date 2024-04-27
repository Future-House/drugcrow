FROM postgres:latest

ENV POSTGRES_DB=chembl_34
ENV POSTGRES_USER=admin
ENV POSTGRES_PASSWORD=password

RUN apt-get update && apt-get install -y \
    wget \
    ca-certificates \
    tar

WORKDIR /docker-entrypoint-initdb.d

RUN wget -q https://ftp.ebi.ac.uk/pub/databases/chembl/ChEMBLdb/latest/chembl_34_postgresql.tar.gz

RUN tar -xzf chembl_34_postgresql.tar.gz --strip-components=1

ENV PGDATA /var/lib/postgresql/data

EXPOSE 5432
