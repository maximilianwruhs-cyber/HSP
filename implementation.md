# Implementation Details & Architecture

Dieses Dokument beschreibt das Datenmodell, die Schnittstellen und die interne Logik der Hardware-Sonification-Pipeline.

## 1. Datenmodell

Die Pipeline verarbeitet Hardware-Metriken in einer erweiterten Dictionary-Struktur, bevor sie in MIDI-Signale umgewandelt werden.

- Rohdaten:
  - cpu_usage: float (0-100)
  - ram_usage: float (0-100)
  - gpu_usage: float (0-100)
- Timing: BPM ist als konstanter Integer definiert (Standard: 120), daraus wird die Beat-Dauer berechnet.
- Smoothing: Pro Metrik speichert eine deque die letzten n Werte (Standard: 5) und berechnet einen gleitenden Durchschnitt.

## 2. Schnittstellen & Mapping

Die Pipeline nutzt lokale System-Schnittstellen ohne externe Web-APIs.

| Hardware-Metrik | Extrahierung | MIDI-Parameter | Bemerkung |
| --- | --- | --- | --- |
| CPU | psutil | Note + optional Pitch Bend | Auf Tonleiter quantisiert, optional mikrotönale Feinanpassung |
| RAM | psutil | Velocity | Lautstärke/Anschlagstärke 0-127 |
| GPU | nvidia-smi via subprocess | CC1 Modulation | Timbre/Modulation |

## 3. Ausführungs-Roadmap

- Paket 1 Host-Setup (`setup_host.sh`): Abhängigkeiten installieren, NVIDIA Toolkit konfigurieren, FluidSynth starten.
- Paket 2 Code-Refinement (`sonification_pipeline.py`): Hauptloop, Smoothing, Mapping, Pitch-Bend.
- Paket 3 Docker (`Dockerfile`, `docker_run.sh`): Container mit GPU- und Audio-Passthrough.
- Paket 4 Tests (`test_sonification.py`): Unit-Tests für Smoothing, Mapping und GPU-Extraction.
- Paket 5 Advanced Harmonization: Vorbereitung für externes LV2-Pitch-Correction-Routing (z. B. Carla + x42-autotune).

## 4. Tech Summary

Die Architektur integriert FluidSynth als MIDI-Synthesizer mit SoundFont-Ausgabe, Docker-Deployment mit Hardware-Passthrough und Metrik-Smoothing für organischere Übergänge. Das Ziel ist robuste Echtzeit-Sonification mit musikalisch nutzbarer Ausgabe statt roher Lastsprünge.
