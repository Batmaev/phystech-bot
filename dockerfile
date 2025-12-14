FROM public.ecr.aws/docker/library/python:3.12-alpine

WORKDIR /noflood-bot
COPY . .
RUN pip3 install -r requirements.txt
RUN python3 -m src.utils.db
