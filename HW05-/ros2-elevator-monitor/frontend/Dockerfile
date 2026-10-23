# =====================================================================
# web-frontend : Nginx
# 職責：託管前端監控儀表板，並提供反向代理 (/api, /rosbridge)
# =====================================================================
FROM nginx:1.25-alpine

LABEL maintainer="SE-HW05" \
      description="Nginx frontend + reverse proxy for elevator monitor"

ENV TZ=Asia/Taipei

# 移除預設站台設定，改用自訂 nginx.conf
RUN rm -f /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/nginx.conf
COPY proxy_common.conf /etc/nginx/conf.d/proxy_common.conf
COPY src /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD wget -q --spider http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]