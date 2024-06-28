FROM python:3.11-alpine

RUN apk add --virtual build-deps
RUN apk add python3-dev musl-dev linux-headers postgresql-dev geos-dev

RUN pip3 install --no-cache-dir poetry

COPY pyproject.toml /app/pyproject.toml
RUN sed -i '0,/version = .*/ s//version = "0.1.0"/' /app/pyproject.toml && touch /app/README.md

WORKDIR /app
RUN poetry config virtualenvs.create false
RUN poetry install

COPY README.md /app/README.md
COPY urban_api /app/urban_api

RUN pip3 install .

echo "launch_urban_api &" > /entrtypoint.sh
echo "URBAN_API_PID=$!" >> /entrtypoint.sh
echo "launch_city_api &" >> /entrtypoint.sh
echo "CITY_API_PID=$!" >> /entrtypoint.sh
echo "while true; do" >> /entrtypoint.sh
echo "ps | grep $URBAN_API_PID > /dev/null && ps | grep $CITY_API_PID > /dev/null" > /entrtypoint.sh
echo "sleep 5" >> /entrtypoint.sh
echo "done" >> /entrtypoint.sh

CMD ["/entrtypoint.sh"]
