FROM python:3.12-slim
# GPU libs (for `docker run --gpus all`): docker build --build-arg GPU=1 .
ARG GPU=
RUN pip install --no-cache-dir faster-whisper \
 && if [ -n "$GPU" ]; then pip install --no-cache-dir nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"; fi
# large-v3 baked into the image (outside the /data volume so the volume can't hide it)
ENV HF_HOME=/opt/hf
RUN python -c "from faster_whisper.utils import download_model; download_model('large-v3')"
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir .
VOLUME /data
EXPOSE 8765
CMD ["craig-transcriber", "--host", "0.0.0.0", "--data", "/data/work", "--no-browser"]
