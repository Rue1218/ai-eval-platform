# 构建阶段
FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY main.go ./
RUN go build -o /out/stress .

# 运行阶段
FROM alpine:3.20
RUN adduser -D -u 10001 app
USER app
COPY --from=build /out/stress /usr/local/bin/stress
EXPOSE 19090
CMD ["stress"]
