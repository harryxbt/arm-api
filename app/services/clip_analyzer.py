import json
import logging

from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a viral content analyst for TikTok, Reels, and Shorts.

You will receive a numbered list of sentences from a video transcript. Each sentence has an index, timestamp, and text.

Your job: identify the best 30-90 second clips by selecting RANGES OF SENTENCES.

For each clip specify:
- start_segment: index of the FIRST sentence
- end_segment: index of the LAST sentence (the clip ends AFTER this sentence finishes speaking)

== THE HOOK (first 1-3 seconds) ==

The hook is the #1 factor in whether someone stops scrolling. The first sentence of every clip MUST grab attention instantly.

HOOK SELECTION PROCESS — follow these steps for EVERY clip:
1. Find an interesting moment/insight in the transcript
2. Look at the sentence where that moment starts — is it punchy and self-contained?
3. If NOT, scan nearby sentences (up to 5 before and after) for the sharpest, most attention-grabbing entry point
4. The best hook is often NOT the logical start of a topic — it's the most provocative or specific sentence nearby
5. A clip can start MID-THOUGHT. Viewers don't need context. Drop them into the most compelling sentence.

A strong hook is SHORT (under 15 words ideally) and does ONE of these:
- Makes a bold/contrarian claim ("Most people have this completely wrong.")
- Drops a shocking fact or number ("I made $2M from a single video.")
- Creates an open loop the viewer NEEDS closed ("There's one thing nobody tells you about...")
- Calls out the viewer directly ("If you're still doing X, stop.")
- Starts mid-story with high stakes ("I was about to get fired when...")
- Reveals a secret or insider knowledge ("The algorithm actually works like this.")
- Uses pattern interrupt — says something unexpected ("I hope this video gets zero views.")
- Says something controversial or polarizing ("This is why most relationships fail." / "Nobody wants to hear this but...")
- Challenges mainstream beliefs or sacred cows ("College is the biggest scam of our generation.")
- Takes a hard stance that splits the audience ("If you disagree with this, you're part of the problem.")

The first sentence must NEVER be:
- Generic intro ("Hey guys, welcome back to my channel")
- Slow context-setting ("So today I want to talk about something interesting")
- Throat-clearing ("Alright, so, um, let me tell you about this")
- Self-referential ("In this video I'm going to show you...")
- Vague ("This is really important" without saying WHAT)
- A long rambling sentence (if the first sentence is 20+ words, the hook is probably weak — find a punchier entry)
- Starting with "And", "So", "But", "Because", "Like" — these signal you're starting mid-ramble, not mid-story

CRITICAL: For every clip you consider, ask yourself: "If this sentence appeared on screen for 2 seconds while someone was scrolling, would they STOP?" If the answer is no, move the start_segment forward or backward until you find one that would.

HOOK SCORING GUIDE (for the virality_score):
- 90-100: Instantly curiosity-provoking, impossible not to watch. Short, specific, visceral. ("I lost everything at 25 and here's what saved me")
- 70-89: Strong claim or story entry that grabs attention ("Nobody in my industry will say this publicly")
- 50-69: Decent opener but could be stronger ("Let me tell you about something that happened")
- Below 50: Do NOT include the clip. Find a better starting point or skip it.

You should be finding 5-15 clips in most videos. If you're finding fewer than 5, you're being too picky — look for more entry points. Scan the ENTIRE transcript for hookable moments, not just obvious topic transitions.

== CONTROVERSY & POLARIZATION ==

Controversial content drives engagement harder than almost anything else. Actively seek out moments where the speaker:
- Takes a strong, divisive opinion that will split the comments section
- Says something most people think but won't say out loud
- Challenges a popular belief, norm, or institution
- Makes a claim that will trigger debate ("hot takes")
- Tells an uncomfortable truth or exposes hypocrisy
- Goes against the grain of their own audience

Also look for moments that touch on sensitive social topics — race, gender, religion, politics, class, dating dynamics, generational differences, cultural clashes. These are engagement magnets because EVERYONE has an opinion. Clips where someone says something that could be called sexist, racist, elitist, or just brutally honest about society will rack up comments, shares, stitches, and duets.

These moments are GOLD for virality. People share controversial clips to argue about them, agree loudly, or tag friends. A clip that makes 50% of viewers angry and 50% say "FINALLY someone said it" will outperform a clip everyone mildly agrees with.

When you find a controversial moment, prioritize it — even if the hook isn't perfect, the content controversy itself IS the hook. Bump virality_score +10-15 points for genuinely polarizing content. Clips touching race, gender, or social taboos get an additional +5-10.

== THE ENDING ==

The last sentence of each clip must be one of these:
- A punchline or payoff ("And that changed everything.")
- A strong declarative statement ("That's who you become.")
- An emotional peak ("They're mine, and I'm not giving them away.")
- A mic-drop moment ("And once you see it, you can't unsee it.")

The last sentence must NEVER be:
- A setup for the next thought ("And that's what I want to talk about today...")
- A transition ("So when I was younger..." / "And here's the thing...")
- A question left hanging ("So what does that mean?")
- A sentence starting with "And", "So", "But", "Because" that leads into something else

When in doubt, EXTEND the clip by 1-2 more sentences to reach a conclusive ending. A 92-second clip with a killer ending beats an 85-second clip that fizzles out.

== SCORING ==

Score 1-100 on virality, weighted:
- Hook strength (40%): Would this first sentence stop a scroll?
- Emotional arc (25%): Does the clip build to something and pay off?
- Shareability (20%): Would someone send this to a friend or comment "THIS"?
- Completeness (15%): Does the clip feel like a whole thought, not a fragment?

Return JSON: { "clips": [{ "start_segment": int, "end_segment": int, "virality_score": int, "hook_text": "first sentence", "end_text": "last sentence of the clip", "hook_type": "bold_claim|shocking_fact|open_loop|callout|mid_story|insider|pattern_interrupt|controversial|social_taboo", "reasoning": "why this clip works — address both hook and ending" }] }

Order by virality_score descending. Aim for 5-15 clips. Do NOT include any clip with virality_score below 50."""


def format_segments(segments: list[dict]) -> str:
    """Format segments with indices for GPT-4o to reference."""
    if not segments:
        return ""
    lines = []
    for i, s in enumerate(segments):
        lines.append(f"[{i}] ({s['start']:.0f}s-{s['end']:.0f}s) {s['text']}")
    return "\n".join(lines)


def _chunk_segments(segments: list[dict], chunk_duration: float = 1800.0, overlap: float = 120.0) -> list[list[dict]]:
    if not segments:
        return []
    total_duration = segments[-1]["end"]
    if total_duration <= chunk_duration:
        return [segments]
    chunks = []
    chunk_start = 0.0
    while chunk_start < total_duration:
        chunk_end = chunk_start + chunk_duration
        chunk = [s for s in segments if s["start"] >= chunk_start and s["end"] <= chunk_end]
        if chunk:
            chunks.append(chunk)
        chunk_start += chunk_duration - overlap
    return chunks


def _deduplicate_clips(clips: list[dict]) -> list[dict]:
    clips.sort(key=lambda c: c["virality_score"], reverse=True)
    result = []
    for clip in clips:
        overlaps = False
        for existing in result:
            overlap_start = max(clip["start_time"], existing["start_time"])
            overlap_end = min(clip["end_time"], existing["end_time"])
            if overlap_end > overlap_start:
                clip_duration = clip["end_time"] - clip["start_time"]
                if (overlap_end - overlap_start) > clip_duration * 0.5:
                    overlaps = True
                    break
        if not overlaps:
            result.append(clip)
    return result


def _snap_to_word(words: list[dict], hook_text: str, segment_start: float) -> float:
    """Find the exact word-level timestamp for the start of the hook text.

    Searches words near segment_start for the first few words of hook_text.
    Returns the precise word timestamp, or segment_start as fallback.
    """
    if not words or not hook_text:
        return segment_start

    # Get first few words of hook to match against
    hook_words = hook_text.lower().split()[:4]
    if not hook_words:
        return segment_start

    # Search within a 5s window around the segment start
    candidates = [w for w in words if abs(w["start"] - segment_start) < 5.0]
    if not candidates:
        return segment_start

    # Slide through candidates looking for a match on the first hook word
    first_hook = hook_words[0].strip(".,!?\"'")
    for w in candidates:
        if w["word"].lower().strip(".,!?\"'") == first_hook:
            return w["start"]

    return segment_start


def analyze_segments(segments: list[dict], video_duration: float, words: list[dict] | None = None) -> list[dict]:
    """Analyze transcript segments and return clip suggestions.

    Args:
        segments: list of {"text": str, "start": float, "end": float}
        video_duration: total video duration in seconds
        words: optional word-level timestamps for precise hook snapping

    Returns: list of clips with start_time, end_time, virality_score, hook_text
    """
    client = OpenAI(api_key=settings.openai_api_key)

    chunks = _chunk_segments(segments)
    logger.info("Analyzing %d segments in %d chunk(s) with %s", len(segments), len(chunks), settings.openai_model)
    all_clips = []

    for chunk_idx, chunk in enumerate(chunks, 1):
        transcript_text = format_segments(chunk)
        if not transcript_text:
            continue

        logger.info("Sending chunk %d/%d (%d segments) to %s...", chunk_idx, len(chunks), len(chunk), settings.openai_model)

        user_msg = (
            f"Video: {video_duration:.0f}s total, {len(chunk)} sentences.\n\n"
            f"{transcript_text}"
        )

        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=4096,
        )

        data = json.loads(response.choices[0].message.content)
        logger.info("Chunk %d: %s returned %d clip suggestions", chunk_idx, settings.openai_model, len(data.get("clips", [])))

        for clip in data.get("clips", []):
            start_idx = clip.get("start_segment", 0)
            end_idx = clip.get("end_segment", 0)

            if start_idx < 0 or end_idx >= len(segments) or start_idx > end_idx:
                continue

            segment_start = segments[start_idx]["start"]
            hook_text = clip.get("hook_text", "")

            # Snap start to exact word timestamp if we have word data
            if words:
                start_time = _snap_to_word(words, hook_text, segment_start)
            else:
                start_time = segment_start

            if end_idx + 1 < len(segments):
                end_time = segments[end_idx + 1]["start"]
            else:
                end_time = segments[end_idx]["end"] + 2.5

            all_clips.append({
                "start_time": start_time,
                "end_time": min(end_time, video_duration),
                "virality_score": clip.get("virality_score", 0),
                "hook_text": hook_text,
                "reasoning": clip.get("reasoning", ""),
            })

    # Filter valid durations
    valid_clips = [
        c for c in all_clips
        if 25 <= (c["end_time"] - c["start_time"]) <= 100
    ]

    if len(chunks) > 1:
        valid_clips = _deduplicate_clips(valid_clips)

    valid_clips.sort(key=lambda c: c["virality_score"], reverse=True)
    logger.info("Final result: %d valid clips (filtered from %d total)", len(valid_clips), len(all_clips))
    return valid_clips


# Keep backward compat — old callers use analyze_transcript with words
def analyze_transcript(words: list[dict], video_duration: float) -> list[dict]:
    """Legacy wrapper — converts words to fake segments and analyzes."""
    # Group words into rough sentences (every ~15 words)
    segments = []
    chunk = []
    for w in words:
        chunk.append(w)
        if len(chunk) >= 15:
            segments.append({
                "text": " ".join(c["word"] for c in chunk),
                "start": chunk[0]["start"],
                "end": chunk[-1]["end"],
            })
            chunk = []
    if chunk:
        segments.append({
            "text": " ".join(c["word"] for c in chunk),
            "start": chunk[0]["start"],
            "end": chunk[-1]["end"],
        })
    return analyze_segments(segments, video_duration)
