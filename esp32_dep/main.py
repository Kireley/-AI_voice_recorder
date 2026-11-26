import gc
import os
import socket
import struct
import time
import network
from machine import Pin, I2S, SDCard
from config import (
    WIFI_SSID, WIFI_PASS, FILE_PATH, SAMPLE_RATE, UPLOAD_TOKEN, PC_IP, PC_PORT
)

# Максимальная длительность одной записи: защита от зажатой кнопки
MAX_RECORD_SECONDS = 120
MAX_RECORD_BYTES = SAMPLE_RATE * 2 * MAX_RECORD_SECONDS

# --- ПИНЫ УПРАВЛЕНИЯ ---
button = Pin(4, Pin.IN, Pin.PULL_UP)  # Кнопка между GPIO 4 и GND
led = Pin(2, Pin.OUT)                 # Встроенный синий светодиод на плате
led.value(0)


def connect_wifi(timeout_s=15):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Подключаемся к Wi-Fi...")
        wlan.connect(WIFI_SSID, WIFI_PASS)
        t0 = time.ticks_ms()
        while not wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), t0) > timeout_s * 1000:
                print("Таймаут подключения к Wi-Fi")
                led.value(0)
                return False
            led.value(not led.value())
            time.sleep(0.25)

    try:
        wlan.config(pm=wlan.PM_NONE)
    except Exception:
        pass
    led.value(0)
    print("Wi-Fi подключен, IP:", wlan.ifconfig()[0])
    return True


def create_wav_header(sample_rate, bits_per_sample, num_channels, data_size):
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", data_size + 36, b"WAVE",
        b"fmt ", 16, 1, num_channels, sample_rate,
        byte_rate, block_align, bits_per_sample,
        b"data", data_size
    )


def record_while_pressed():
    gc.collect()
    audio_in = I2S(
        0, sck=Pin(26), ws=Pin(25), sd=Pin(33),
        mode=I2S.RX, bits=16, format=I2S.MONO, rate=SAMPLE_RATE, ibuf=16384
    )
    buf = bytearray(4096)

    # Прогреваем микрофон (отбрасываем первые ~150-250 мс пустого старта)
    for _ in range(3):
        audio_in.readinto(buf)

    total_bytes = 0
    led.value(1)
    print("Запись пошла...")

    with open(FILE_PATH, "wb") as f:
        f.write(b"\x00" * 44)
        while button.value() == 0:
            n = audio_in.readinto(buf)
            if n > 0:
                f.write(buf[:n])
                total_bytes += n
                if total_bytes >= MAX_RECORD_BYTES:
                    print("Достигнут лимит записи, останавливаемся")
                    break

        f.seek(0)
        f.write(create_wav_header(SAMPLE_RATE, 16, 1, total_bytes))

    audio_in.deinit()
    led.value(0)
    gc.collect()
    print("Запись завершена, байт:", total_bytes)
    return total_bytes > 10000


def send_and_delete(filepath):
    gc.collect()
    file_size = os.stat(filepath)[6]
    filename = f"rec_{time.ticks_ms()}.wav"
    sock = None
    try:
        t0 = time.ticks_ms()
        print(f"Отправляем {file_size} байт на сервер...")
        sock = socket.socket()
        sock.settimeout(30.0)
        sock.connect((PC_IP, PC_PORT))

        headers = (
            f"POST /upload HTTP/1.1\r\n"
            f"Host: {PC_IP}:{PC_PORT}\r\n"
            f"X-Filename: {filename}\r\n"
            f"X-Upload-Token: {UPLOAD_TOKEN}\r\n"
            f"Content-Type: audio/wav\r\n"
            f"Content-Length: {file_size}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode()
        sock.write(headers)

        buf = bytearray(32768)
        mv = memoryview(buf)
        total_sent = 0

        with open(filepath, "rb") as f:
            while True:
                n = f.readinto(buf)
                if not n:
                    break
                sent = 0
                while sent < n:
                    res = sock.write(mv[sent:n])
                    if res is None or res == 0:
                        time.sleep_ms(5)
                        continue
                    sent += res
                total_sent += n
                led.value(not led.value())

        resp = sock.readline().decode()
        dt = time.ticks_diff(time.ticks_ms(), t0) / 1000
        print(f"Готово за {dt:.1f} сек! Ответ:", resp.strip())
        if "200 OK" in resp:
            os.remove(filepath)
    except Exception as e:
        print("Ошибка отправки:", repr(e))
    finally:
        led.value(0)
        if sock:
            sock.close()
        gc.collect()


# --- ЗАПУСК ---
try:
    sd = SDCard(slot=2, sck=Pin(18), mosi=Pin(23), miso=Pin(19), cs=Pin(5), freq=10000000)
    os.mount(sd, "/sd")
except OSError as e:
    print("SD уже примонтирована или ошибка инициализации:", repr(e))

connect_wifi()
print("Система готова! Зажмите кнопку на GPIO 4.")

while True:
    if button.value() == 0:
        time.sleep_ms(30)
        if button.value() == 0:
            if record_while_pressed():
                if connect_wifi():
                    send_and_delete(FILE_PATH)
    time.sleep_ms(30)
