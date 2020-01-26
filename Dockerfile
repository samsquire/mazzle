FROM ubuntu:latest
ENV HTTPS_PROXY "https://127.0.0.1:3128"
ENV https_proxy "https://127.0.0.1:3128"
ENV HTTP_PROXY "https://127.0.0.1:3128"
ENV http_proxy "https://127.0.0.1:3128"
RUN echo "Acquire::http::Proxy \"http://localhost:3128/\";" > /etc/apt/apt.conf.d/proxy.conf

RUN apt-get update
RUN apt-get install python3 python3-pip -y
RUN apt-get install git -y
RUN apt-get install nodejs -y
RUN apt-get install npm -y
RUN mkdir /opt/devops-pipeline
COPY . /opt/devops-pipeline
WORKDIR /opt/devops-pipeline
RUN pip3 install -r requirements.txt 
RUN cd devops_pipeline/web && npm run build 

ENTRYPOINT ["python3", "/opt/devops-pipeline/devops_pipeline/devops-pipeline"]



