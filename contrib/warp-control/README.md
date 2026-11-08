# warp-control

Gives Downtify a new exit IP when YouTube flags the current one with
"Sign in to confirm you're not a bot". It runs inside a Cloudflare WARP
proxy container (`caomingjun/warp`) and reconnects WARP on
`POST /rotate`, which changes the exit IP in 2–3 seconds.

```yaml
services:
  warp:
    image: caomingjun/warp:latest
    entrypoint: ["/bin/bash", "-c", "python3 /warp-control/warp_control.py & exec /entrypoint.sh"]
    environment:
      WARP_CONTROL_TOKEN: ${WARP_CONTROL_TOKEN}
    volumes:
      - ./contrib/warp-control:/warp-control:ro
    # no `ports:` - only Downtify, on the Docker network, should reach it

  downtify:
    environment:
      DOWNTIFY_PROXY: "socks5h://warp:1080"
      DOWNTIFY_IP_ROTATE_URL: "http://warp:8081/rotate"
      DOWNTIFY_IP_ROTATE_TOKEN: ${WARP_CONTROL_TOKEN}
```

Put a random `WARP_CONTROL_TOKEN` in the compose `.env`
(`openssl rand -hex 32`). Calls without it get `401`.
