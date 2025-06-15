FROM ubuntu:latest

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8
ENV TZ=America/New_York
ENV RUN_API_SOLVER=false
ENV HOME="root"

RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get install -y --no-install-recommends tzdata locales

RUN sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && locale-gen
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
RUN echo "LC_ALL=en_US.UTF-8" >> /etc/environment
RUN echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen
RUN echo "LANG=en_US.UTF-8" > /etc/locale.conf
RUN locale-gen en_US.UTF-8

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    curl \
    wget \
    screen \
    sudo \
    xrdp \
    xfce4 \
    xorgxrdp \
    dbus-x11 \
    xfce4-terminal \
    python3-pip \
    ca-certificates \
    xvfb

RUN apt remove -y light-locker xscreensaver && \
    apt autoremove -y && \
    rm -rf /var/cache/apt /var/lib/apt/lists

RUN apt-get update && \
    wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt-get install -y ./google-chrome-stable_current_amd64.deb && \
    rm ./google-chrome-stable_current_amd64.deb

COPY ./run.sh /usr/bin/
RUN chmod +x /usr/bin/run.sh

EXPOSE 3389
ENTRYPOINT ["/usr/bin/run.sh"]
