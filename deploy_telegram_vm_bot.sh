
#!/bin/bash

# Telegram VM Bot - Script de Despliegue Automático
# Este script instala dependencias y configura el servicio
# Los archivos del proyecto deben estar ya subidos a /home/eljoker63/telegram-docker-vm
# El token de Telegram se lee automáticamente del archivo .env
# Ejecutar como root: sudo bash deploy_telegram_vm_bot.sh

# Colores para la salida
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Función para mostrar mensajes
function echo_color {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Función para verificar si un paquete está instalado
function is_package_installed {
    local package=$1
    dpkg -l "$package" 2>/dev/null | grep -q "^ii"
    return $?
}

# Función para instalar paquetes solo si no están instalados
function install_packages_if_missing {
    local packages=("$@")
    local to_install=()

    echo_color $YELLOW "🔍 Verificando paquetes instalados..."

    for package in "${packages[@]}"; do
        if is_package_installed "$package"; then
            echo_color $GREEN "✅ $package ya está instalado"
        else
            to_install+=("$package")
            echo_color $YELLOW "📦 $package necesita instalación"
        fi
    done

    if [ ${#to_install[@]} -eq 0 ]; then
        echo_color $GREEN "🎉 Todos los paquetes ya están instalados"
        return 0
    fi

    echo_color $GREEN "📦 Instalando ${#to_install[@]} paquete(s): ${to_install[*]}"
    apt install -y -qq "${to_install[@]}"
    return $?
}

# Verificar si se ejecuta como root
if [ "$(id -u)" -ne 0 ]; then
    echo_color $RED "❌ Este script debe ejecutarse como root"
    echo_color $YELLOW "💡 Ejecuta: sudo bash $0"
    exit 1
fi

echo_color $GREEN "✅ Iniciando despliegue automático..."
echo_color $YELLOW "📋 Esto puede tomar unos minutos..."

# Verificar que existe el archivo .env y contiene el token
if [ ! -f "/home/eljoker63/telegram-docker-vm/.env" ]; then
    echo_color $RED "❌ No se encuentra el archivo .env en /home/eljoker63/telegram-docker-vm"
    echo_color $YELLOW "💡 Asegúrate de que el archivo .env esté subido con la variable TELEGRAM_TOKEN"
    exit 1
fi

# Leer el token del archivo .env
TELEGRAM_TOKEN=$(grep "^TELEGRAM_TOKEN=" /home/eljoker63/telegram-docker-vm/.env | cut -d'=' -f2 | tr -d '"' | tr -d "'")
if [ -z "$TELEGRAM_TOKEN" ]; then
    echo_color $RED "❌ No se pudo leer TELEGRAM_TOKEN del archivo .env"
    echo_color $YELLOW "💡 Verifica que el archivo .env contenga: TELEGRAM_TOKEN=tu_token_aqui"
    exit 1
fi

echo_color $GREEN "✅ Token de Telegram encontrado en .env"

# 1. Actualizar sistema
echo_color $GREEN "🔄 Actualizando sistema..."
apt update -qq && apt upgrade -y -qq
if [ $? -ne 0 ]; then
    echo_color $RED "❌ Falló la actualización del sistema"
    exit 1
fi

# 2. Instalar dependencias
echo_color $GREEN "📦 Instalando dependencias..."

# Handle containerd.io conflict
echo_color $YELLOW "🔧 Resolviendo conflicto de containerd.io..."
if dpkg -l | grep -q containerd.io; then
    echo_color $YELLOW "📦 Eliminando containerd.io para evitar conflictos..."
    apt remove -y -qq containerd.io
    if [ $? -ne 0 ]; then
        echo_color $RED "❌ Falló al eliminar containerd.io"
        exit 1
    fi
fi

# Install dependencies (only if not already installed)
install_packages_if_missing docker.io python3-pip git curl wget
if [ $? -ne 0 ]; then
    echo_color $RED "❌ Falló la instalación de dependencias"
    exit 1
fi

# 3. Instalar dependencias Python
echo_color $GREEN "🐍 Instalando dependencias Python..."

# Check if Python packages are already installed
PYTHON_PACKAGES_INSTALLED=true
if ! python3 -c "import docker, telegram, dotenv" 2>/dev/null; then
    PYTHON_PACKAGES_INSTALLED=false
fi

if [ "$PYTHON_PACKAGES_INSTALLED" = true ]; then
    echo_color $GREEN "✅ Dependencias Python ya están instaladas"
else
    echo_color $YELLOW "📦 Instalando dependencias Python..."
    pip3 install --root-user-action=ignore -q python-telegram-bot docker python-dotenv
    if [ $? -ne 0 ]; then
        echo_color $RED "❌ Falló la instalación de dependencias Python"
        exit 1
    fi
    echo_color $GREEN "✅ Dependencias Python instaladas"
fi

# 4. Ir al directorio del proyecto
echo_color $GREEN "📁 Accediendo al directorio del proyecto..."
cd /home/eljoker63/telegram-docker-vm

# 5. Crear servicio systemd
echo_color $GREEN "🔧 Creando servicio systemd..."
cat > /etc/systemd/system/telegram-vm-bot.service << EOF
[Unit]
Description=Telegram VM Bot Service
After=docker.service
Requires=docker.service

[Service]
User=root
WorkingDirectory=/home/eljoker63/telegram-docker-vm
ExecStart=/usr/bin/python3 /home/eljoker63/telegram-docker-vm/src/bot.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# 6. Iniciar y habilitar el servicio
echo_color $GREEN "🚀 Iniciando servicio..."
systemctl daemon-reload
systemctl enable telegram-vm-bot
systemctl start telegram-vm-bot

# 7. Verificar estado
sleep 3
STATUS=$(systemctl is-active telegram-vm-bot)
if [ "$STATUS" = "active" ]; then
    echo_color $GREEN "✅ ¡Bot desplegado exitosamente!"
    echo_color $YELLOW "📊 Estado del servicio: $STATUS"
    echo_color $GREEN "🎉 Puedes empezar a usar el bot en Telegram"
else
    echo_color $RED "❌ Error al iniciar el servicio"
    echo_color $YELLOW "📋 Revisa los logs con:"
    echo_color $YELLOW "journalctl -u telegram-vm-bot -f"
fi

# 8. Mostrar información final
echo_color $GREEN "📋 Resumen de la instalación:"
echo_color $YELLOW "📁 Directorio: /home/eljoker63/telegram-docker-vm"
echo_color $YELLOW "🔄 Servicio: telegram-vm-bot"
echo_color $YELLOW "📊 Logs: journalctl -u telegram-vm-bot -f"
echo_color $YELLOW "🚀 Comandos disponibles en Telegram:"
echo_color $YELLOW "  /start - Menú principal"
echo_color $YELLOW "  /create - Crear VM"
echo_color $YELLOW "  /stop <id> - Detener VM"
echo_color $YELLOW "  /start <id> - Iniciar VM"
echo_color $YELLOW "  /remove <id> - Eliminar VM"
echo_color $YELLOW "  /exec <id> <cmd> - Ejecutar comando"
echo_color $YELLOW "  /status <id> - Estado de VM"

echo_color $GREEN "✅ ¡Instalación completada!"
EOF
<line_count>350</line_count>
