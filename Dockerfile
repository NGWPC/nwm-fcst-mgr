FROM registry.sh.nextgenwaterprediction.com/ngwpc/nwm-ngen/ngen:latest

COPY requirements.txt .
RUN set -eux; \
	\
    pip3 install -r requirements.txt ; \
    pip3 cache purge ; \
    rm --force requirements.txt


COPY . /ngen-app/ngen-fcst/
COPY ./docker/run-ngen-fcst.sh /ngen-app/bin/
RUN set -eux; \
	\
    chmod +x /ngen-app/bin/run-ngen-fcst.sh

WORKDIR /

ENTRYPOINT [ "/ngen-app/bin/run-ngen-fcst.sh" ] 
