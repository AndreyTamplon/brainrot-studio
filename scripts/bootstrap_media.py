"""Download attributed preset assets. No credentials, browser cookies or paid downloads."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from bs4 import BeautifulSoup

from brainrot import assets, config, media

GAMEPLAY_REPO = "https://github.com/Srinivasan-78/study-brainrot-generator"
GAMEPLAY_COMMIT = "d887eefc3a74bd29760c5c8fb7c943b4b7a40303"


async def gameplay(data):
    for prefix, identifier, name, skip in [
        ("part", "minecraft-coast", "Minecraft · Побережье", 0),
        ("partty", "minecraft-caves", "Minecraft · Пещеры", 10),
    ]:
        target = config.DATA / "media" / f"{identifier}.mp4"
        if not target.exists():
            pending_video = target.with_suffix(".pending.mp4")
            inputs = []
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                for index in range(2):
                    path = config.DATA / "cache" / f"gameplay-{prefix}{index:02}.mp4"
                    if not path.exists():
                        url = f"https://raw.githubusercontent.com/Srinivasan-78/study-brainrot-generator/{GAMEPLAY_COMMIT}/assets/{prefix}_{index:02}.mp4"
                        pending = path.with_suffix(".download")
                        async with client.stream("GET", url) as response:
                            response.raise_for_status()
                            with pending.open("wb") as handle:
                                async for chunk in response.aiter_bytes():
                                    handle.write(chunk)
                        await media.probe(pending)
                        pending.replace(path)
                    info = await media.probe(path)
                    if info["duration"] < 60:
                        raise RuntimeError("Incomplete gameplay source")
                    inputs.extend(["-i", path])
            await media.command(
                "ffmpeg",
                "-v",
                "error",
                "-y",
                *inputs,
                "-filter_complex",
                f"[0:v][1:v]concat=n=2:v=1:a=0,trim=start={skip},setpts=PTS-STARTPTS,fps=30[v]",
                "-map",
                "[v]",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "19",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                pending_video,
                timeout=600,
            )
            if (await media.probe(pending_video))["duration"] < 120:
                raise RuntimeError("Incomplete gameplay transcode")
            pending_video.replace(target)
        thumbnail = target.with_suffix(".jpg")
        await media.command(
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            "18",
            "-i",
            target,
            "-frames:v",
            "1",
            "-vf",
            "scale=270:480",
            thumbnail,
        )
        info = await media.probe(target)
        preset = {
            "id": identifier,
            "name": name,
            "path": str(target.relative_to(config.DATA)),
            "thumbnail": assets.public_url(str(thumbnail.relative_to(config.DATA))),
            "duration": info["duration"],
            "source": GAMEPLAY_REPO + "/tree/" + GAMEPLAY_COMMIT + "/assets",
            "credit": "Study Brainrot Generator · Srinivasan Vijayaraghavan",
            "license": "MIT repository; original footage rights unverified. Local educational demonstration only.",
            "source_files": [f"{prefix}_{i:02}.mp4" for i in range(2)],
            "source_commit": GAMEPLAY_COMMIT,
            "fps": 30,
            "source_fps": 60,
        }
        data["backgrounds"] = [b for b in data["backgrounds"] if b["id"] != identifier] + [preset]
        assets.save_catalog(data)
        print(f"Gameplay ready: {name}, {info['duration']:.1f}s", flush=True)


async def extra_gameplay(data):
    for identifier, name, source_path, author, cached in [
        (
            "cs-surf",
            "CS · Surf",
            "cs_surfing/kuPPZCtLX4w.mp4",
            "freetousegameplay5868",
            "cs-surf-source.mp4",
        ),
        ("subway", "Subway Surfers", "subway_surfers/MXP9qzYpUJM.mp4", "OrbitalNCG", None),
    ]:
        target = config.DATA / "media" / f"{identifier}.mp4"
        url = "https://assets.inkslop.com/video/" + source_path
        if not target.exists():
            local = config.DATA / "cache" / cached if cached else None
            candidate = config.DATA / "cache/subway-candidate.mp4"
            if identifier == "subway" and candidate.exists():
                info = await media.probe(candidate)
                if info["duration"] >= 149:
                    candidate.replace(target)
            if not target.exists():
                pending = target.with_suffix(".pending.mp4")
                await media.command(
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-rw_timeout",
                    "30000000",
                    "-ss",
                    "30",
                    "-i",
                    local if local and local.exists() else url,
                    "-t",
                    "150",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "19",
                    "-vf",
                    "fps=30",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    pending,
                    timeout=600,
                )
                pending.replace(target)
        info = await media.probe(target)
        if info["duration"] < 149:
            raise RuntimeError("Gameplay source is incomplete")
        thumb = target.with_suffix(".jpg")
        await media.command(
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            "18",
            "-i",
            target,
            "-frames:v",
            "1",
            "-vf",
            "scale=270:480:force_original_aspect_ratio=increase,crop=270:480",
            thumb,
        )
        preset = {
            "id": identifier,
            "name": name,
            "path": str(target.relative_to(config.DATA)),
            "thumbnail": assets.public_url(str(thumb.relative_to(config.DATA))),
            "duration": info["duration"],
            "source": "https://www.youtube.com/watch?v=" + source_path.split("/")[-1][:-4],
            "download_source": url,
            "credit": author + " · via InkSlop Asset Library",
            "license": "CC BY 4.0 (as attributed by InkSlop); https://creativecommons.org/licenses/by/4.0/",
            "modifications": "30-180s excerpt, audio removed, converted to 30 fps; cropped in final render",
        }
        data["backgrounds"] = [b for b in data["backgrounds"] if b["id"] != identifier] + [preset]
        assets.save_catalog(data)
        print(f"Gameplay ready: {name}, {info['duration']:.1f}s", flush=True)


async def main():
    data = assets.catalog()
    async with httpx.AsyncClient(
        timeout=40, follow_redirects=True, headers=assets.HEADERS
    ) as client:
        for identifier, title, name, voice, personality in [
            (
                "stewie",
                "Stewie_Griffin",
                "Стюи",
                "e91c4f5974f149478a35affe820d02ac",
                "Язвительный интеллектуал, короткие колкие реплики",
            ),
            (
                "peter",
                "Peter_Griffin",
                "Питер",
                "b1d36a18f8d84bd59dead30474cbe3d7",
                "Наивный собеседник, нелепые бытовые аналогии",
            ),
            (
                "brian",
                "Brian_Griffin",
                "Брайан",
                "c8e60c3921db40b5b69fbf320deb0c26",
                "Спокойный скептик, уточняет и объясняет",
            ),
        ]:
            existing = next((s for s in data["speakers"] if s["id"] == identifier), None)
            voice_config = {
                "voice": voice,
                "tts_model": "fish-audio/s2.1-pro",
                "voice_label": "Fish Audio · community",
                "voice_source": "https://fish.audio/m/" + voice + "/",
                "languages": ["ru", "en"] if identifier in {"peter", "stewie"} else ["en"],
            }
            if identifier == "stewie":
                voice_config["voices_by_language"] = {
                    "ru": "3756ec7a28f34c7f86c9b10350af6b5d",
                    "en": voice,
                }
                if (config.DATA / "cache/stewie-ru-b.mp3").exists():
                    voice_config["voice_previews"] = {"ru": "cache/stewie-ru-b.mp3"}
            if identifier == "peter":
                voice_config["voices_by_language"] = {
                    "ru": "d986dd774dc3473685afde6b54756a57",
                    "en": voice,
                }
                if (config.DATA / "cache/peter-ru-preview.mp3").exists():
                    voice_config["voice_previews"] = {"ru": "cache/peter-ru-preview.mp3"}
            if existing:
                existing.update(voice_config)
                assets.save_catalog(data)
                continue
            page_url = "https://en.wikipedia.org/wiki/" + title
            response = await client.get(page_url)
            response.raise_for_status()
            image = BeautifulSoup(response.text, "html.parser").select_one(".infobox img")
            if not image:
                raise RuntimeError(f"No portrait on {page_url}")
            image_url = "https:" + image["src"] if image["src"].startswith("//") else image["src"]
            path = config.DATA / "media" / f"{identifier}.png"
            await assets.download_image(image_url, path, {"upload.wikimedia.org"})
            data["speakers"].append(
                {
                    "id": identifier,
                    "name": name,
                    "personality": personality,
                    "portrait": str(path.relative_to(config.DATA)),
                    **voice_config,
                    "source": page_url,
                    "license": "Copyrighted character reference; local demonstration only",
                }
            )
            assets.save_catalog(data)
            print(f"Portrait ready: {name}", flush=True)

    # Keep rejected ambient assets for old projects, never offer them as gameplay.
    for background in data["backgrounds"]:
        if background["id"] in {"minecraft-snow", "cubes", "ink"}:
            background["retired"] = True
    assets.save_catalog(data)
    await gameplay(data)
    await extra_gameplay(data)


if __name__ == "__main__":
    asyncio.run(main())
