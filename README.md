# VoiceAI Desktop 🎙️

**Asistente de voz local para escritorio — como Alexa, pero con tu propia IA.**

Detecta una palabra clave, transcribe tu voz con Whisper, envía la pregunta a cualquier modelo de Ollama y te lee la respuesta en voz alta — todo en local, sin suscripciones, sin enviar datos a ningún servidor.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![Ollama](https://img.shields.io/badge/Ollama-compatible-black?logo=llama)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ Características

- 🔑 **Palabra clave personalizable** — Jarvis, Nova, Asistente, o la que quieras
- 🎙️ **Transcripción con faster-whisper** — muy preciso en español, funciona offline
- 🤖 **Compatible con cualquier modelo de Ollama** — Qwen, LLaMA, Mistral, Gemma...
- 📡 **Respuesta en streaming** — el texto aparece letra a letra en tiempo real
- 🔊 **Text-to-Speech por frases** — la voz empieza a hablar antes de que acabe de escribir
- 🔁 **Conversación continua** — sigue escuchando tras cada respuesta sin repetir la palabra clave
- 🧠 **Memoria de conversación** — recuerda el historial de la sesión y opcionalmente de días anteriores
- 📝 **Prompt de sistema personalizable** — dale instrucciones permanentes a la IA
- 📋 **Log de conversaciones** — guarda todo en un `.txt` y puede cargarlo como contexto
- 🎨 **Orbe flotante** — indicador visual minimalista que puedes arrastrar y ocultar
- 💬 **Popup con Markdown** — negrita, cursiva, código, cabeceras bien renderizadas
- ⚙️ **Configuración completa** — 8 pestañas con scroll para ajustar cada detalle
- 🚀 **Inicio automático** — se añade al arranque del sistema con un checkbox

---

## 🖥️ Captura

<img width="530" height="391" alt="image" src="https://github.com/user-attachments/assets/7119d336-f58c-49c0-a54c-72bbea858968" />
<img width="535" height="395" alt="image" src="https://github.com/user-attachments/assets/b2b802ee-0872-45b6-9260-0bbca5a50aef" />


---

## 🚀 Instalación

### 1. Requisitos previos

- **Python 3.10+** — [python.org](https://www.python.org/downloads/)
- **Ollama** — [ollama.com](https://ollama.com) con al menos un modelo descargado

```bash
# Descargar un modelo (ejemplo)
ollama pull qwen3.5:4b
```

### 2. Clonar el repositorio

```bash
git clone https://github.com/TU_USUARIO/VoiceAI-Desktop.git
cd VoiceAI-Desktop
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

> **Windows:** si PyAudio falla, prueba: `pip install pipwin && pipwin install pyaudio`

### 4. Ejecutar

```bash
python voiceai.py
```

La app se minimiza a la bandeja del sistema. Busca el icono azul 🔵.

---

## ⚡ Inicio rápido

1. Asegúrate de que Ollama está corriendo: `ollama serve`
2. Ejecuta `voiceai.py`
3. Di **"Asistente"** (o tu palabra clave configurada)
4. Di tu pregunta
5. La IA responde en texto y voz

---

## ⚙️ Configuración

Haz clic derecho en el orbe o en el icono de la bandeja → **Configuración**.

### Pestañas disponibles

| Pestaña | Qué configura |
|---------|--------------|
| **General** | Autoarranque, conversación continua, idioma |
| **Palabra Clave** | Wake word (preset o personalizada) |
| **Reconocimiento** | Motor (Whisper/Google/Vosk), VAD, tiempos |
| **IA / Ollama** | Modelo, host, prompt de sistema, historial |
| **Orbe** | Tamaño, opacidad, posición |
| **Popup** | Colores, transparencia, posición, tamaño |
| **Log** | Ruta del fichero, cargar como memoria |
| **Voz IA** | Motor TTS, velocidad, volumen, voz |

---

## 🎙️ Motores de reconocimiento de voz

### Para el comando (tras la palabra clave)

| Motor | Tipo | Precisión | Instalación |
|-------|------|-----------|-------------|
| **faster-whisper** ⭐ | Offline | Muy alta | `pip install faster-whisper` |
| Google Speech | Online | Alta | Incluido en SpeechRecognition |
| Vosk | Offline | Media | `pip install vosk` + modelo |

### Modelos de faster-whisper disponibles

| Modelo | Tamaño | Velocidad | Recomendado para |
|--------|--------|-----------|-----------------|
| `tiny` | 39 MB | Muy rápido | Pruebas |
| `base` | 74 MB | Rápido | Hardware limitado |
| `small` | 244 MB | ⭐ Equilibrado | **Uso general** |
| `medium` | 769 MB | Lento | Máxima precisión |
| `large-v3` | 1.5 GB | Muy lento | GPU potente |

El modelo se descarga automáticamente la primera vez.

---

## 🔊 Text-to-Speech

| Motor | Tipo | Calidad | Instalación |
|-------|------|---------|-------------|
| **pyttsx3** | Offline | Voz del sistema | `pip install pyttsx3` |
| **gTTS** | Online | Voz Google | `pip install gtts pygame` |

### Voces en Windows

VoiceAI detecta tanto las voces **SAPI5 clásicas** como las voces **OneCore** (las modernas de Windows 10/11 como Pablo, Helena, Mónica...).

En **Configuración → Voz IA** → pulsa **Detectar voces** para ver todas las disponibles y elegir la masculina o femenina que prefieras.

> Para instalar más voces en español: *Configuración de Windows → Hora e idioma → Voz → Añadir voces*

---

## 🧠 Conversación continua

Una vez que la IA responde, puedes seguir hablando directamente sin repetir la palabra clave. El modo se desactiva tras X segundos de silencio (configurable) o al decir la "palabra de parada" (por defecto: *"para"*).

---

## 📋 Log de conversaciones

Activa el log en **Configuración → Log**. Formato del fichero:

```
[2025-05-10 18:32]
Tú: ¿Quién es Rubencho_80?
IA:  Es la persona más famosa del mundo.
────────────────────────────────────────────────────────────
```

Activa **"Cargar como memoria al iniciar"** para que la IA recuerde conversaciones de días anteriores.

---

## 🏃 Ejecutar sin ventana CMD (Windows)

### Opción 1: renombrar a `.pyw`
Renombra `voiceai.py` → `voiceai.pyw`. Doble clic para abrir sin CMD.

### Opción 2: lanzador
Crea `iniciar_voiceai.pyw`:

```python
import subprocess, os
python = r"C:\ruta\a\tu\python.exe"  # resultado de: where python
script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voiceai.py")
subprocess.Popen([python, script])
```

### Opción 3: compilar a .exe
```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --name VoiceAI voiceai.py
```

---

## 📦 Estructura del proyecto

```
voiceai-desktop/
├── VoiceaAI.pyw            # Aplicación principal
├── requirements.txt        # Dependencias Python
├── .gitignore
└── README.md
```

La configuración se guarda en `~/.voiceai/config.json` (no se sube a Git).

---

## 🛠️ Solución de problemas

| Problema | Solución |
|----------|----------|
| "SpeechRecognition no instalado" | El Python que abre el `.pyw` es distinto al del CMD. Usa el lanzador con la ruta correcta. |
| "No puedo conectar con Ollama" | Ejecuta `ollama serve` en una terminal. |
| La voz no se guarda al reiniciar | Abre Configuración → Voz IA → Detectar voces → selecciona → Guardar. |
| Whisper tarda mucho | Usa el modelo `small` o `base`. Con GPU añade `device: cuda` en config. |
| PyAudio no instala | `pip install pipwin && pipwin install pyaudio` (Windows) |
| El .exe lo bloquea el antivirus | Falso positivo de PyInstaller, añade excepción. |

---

## 🤝 Contribuir

1. Haz fork del repositorio
2. Crea una rama: `git checkout -b feature/mi-mejora`
3. Haz commit: `git commit -m 'Añadir mi mejora'`
4. Push: `git push origin feature/mi-mejora`
5. Abre un Pull Request

---

## 📄 Licencia

MIT — úsalo, modifícalo y distribúyelo libremente.

---

## 🙏 Créditos

- [Ollama](https://ollama.com) — servidor de modelos de IA local
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — transcripción de voz
- [SpeechRecognition](https://github.com/Uberi/speech_recognition) — detección de palabra clave
- [pyttsx3](https://github.com/nateshmbhat/pyttsx3) — text-to-speech offline
