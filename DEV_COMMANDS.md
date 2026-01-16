## PostgreSQL

# activar psql en terminal
$env:Path += ";C:\Program Files\PostgreSQL\18\bin"
psql --version

# conectar a la base de datos
psql -h localhost -U postgres -d gasdb


## Python

# activar entorno virtual
.\.venv\Scripts\Activate.ps1

# levantar API
python -m uvicorn app.main:app --reload


##Alembic

# crear migración
python -m alembic revision -m "convert money fields to integer"

# aplicar migraciones
python -m alembic upgrade head

# estado de migraciones
python -m alembic current
python -m alembic heads
python -m alembic history