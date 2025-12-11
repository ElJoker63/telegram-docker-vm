# Configuración para Coolify - Telegram Docker VM Bot

## Problema Actual

El error `ERROR:docker_handler:Failed to connect to Docker: Error while fetching server API version: ('Connection aborted.', FileNotFoundError(2, 'No such file or directory'))` ocurre porque el contenedor no puede acceder al socket de Docker del host.

## Solución para Coolify

En Coolify, necesitas configurar un **volumen** para montar el socket de Docker del host en el contenedor:

### Configuración de Volúmenes en Coolify:

1. **Agregar un volumen**:
   - **Host Path**: `/var/run/docker.sock`
   - **Container Path**: `/var/run/docker.sock`
   - **Type**: `bind`

2. **Configuración adicional**:
   - Asegúrate de que el usuario dentro del contenedor tenga permisos para acceder al socket
   - El contenedor debe ejecutarse con privilegios o el usuario debe estar en el grupo `docker`

### Configuración de Variables de Entorno:

Necesitas agregar estas variables de entorno en Coolify:

```
TELEGRAM_BOT_TOKEN=tu_token_de_bot_aqui
ADMIN_USER_ID=tu_user_id_aqui
DOCKER_HOST=unix:///var/run/docker.sock
```

### Configuración de Puertos:

- **Puerto 22**: Para SSH (opcional, solo si quieres acceso SSH al contenedor del bot)
- **Puerto 80/443**: Si usas webhooks (no necesario para polling)

## Configuración Alternativa

Si Coolify no permite montar el socket de Docker directamente, puedes:

1. **Usar Docker-in-Docker (DinD)**:
   - Cambiar la imagen base a `docker:dind`
   - Asegurarte de que el servicio Docker esté habilitado

2. **Configurar permisos**:
   - Añadir `USER root` al Dockerfile
   - O añadir el usuario al grupo docker: `RUN usermod -aG docker devuser`

## Notas Importantes

- El bot necesita acceso al daemon de Docker para crear contenedores para los usuarios
- Esto requiere privilegios elevados, así que asegúrate de que tu entorno sea seguro
- En producción, considera usar un socket de Docker dedicado con permisos restringidos