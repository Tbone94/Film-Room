#!/usr/bin/env python3
"""
Commanders Pulse Builder

Builds data/reddit-pulse.json from public community discussion signals.
Designed to run in GitHub Actions. No Reddit account, OAuth token, or API key is required.

Notes:
- This is a best-effort community buzz signal, not a factual truth source.
- The output intentionally avoids storing usernames and long post bodies.
- If Reddit/YARS fails, the script still writes a valid JSON file with error details.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from yars import YARS
except ImportError:
    print("ERROR: yars is not installed. Run: pip install -r requirements.txt")
    sys.exit(1)

OUTPUT_PATH = "data/reddit-pulse.json"
HISTORY_PATH = "data/reddit-pulse-history.json"
TEAM_ID_ESPN = 28
DELAY_BETWEEN_REQUESTS = 4
SELFTEXT_MAX = 280
STALE_AFTER_HOURS = 72

miner = YARS()

SUBS_TO_SCAN = [
    {
        "key": "commanders",
        "subreddit": "Commanders",
        "fetch_categories": ["hot", "new", "top"],
        "fetch_limit": 30,
        "search_queries": [
            "Jayden Daniels",
            "Commanders draft",
            "Commanders offense",
            "Commanders defense",
            "Commanders trade free agent",
            "Commanders injury camp OTA minicamp",
        ],
        "search_limit": 15,
    },
    {
        "key": "nfl_commanders",
        "subreddit": "nfl",
        "fetch_categories": [],
        "fetch_limit": 0,
        "search_queries": ["Commanders", "Washington Commanders", "Jayden Daniels"],
        "search_limit": 20,
    },
    {
        "key": "fantasy_commanders",
        "subreddit": "fantasyfootball",
        "fetch_categories": [],
        "fetch_limit": 0,
        "search_queries": [
            "Jayden Daniels fantasy",
            "Commanders fantasy",
            "McLaurin fantasy",
            "Ekeler Robinson fantasy",
        ],
        "search_limit": 12,
    },
]

# Sports-fan language is noisy/sarcastic. This intentionally measures buzz mood, not truth.
STRONG_POSITIVE = [
    "elite", "beast", "monster", "stud", "generational", "franchise", "pro bowl",
    "all pro", "dominant", "unstoppable", "clutch", "goat", "mvp", "breakout",
    "lethal", "electric", "special", "game changer", "locked in", "baller",
    "built different", "league winner", "super bowl", "playoff", "contender",
]
POSITIVE = [
    "good", "great", "solid", "improving", "better", "growth", "excited", "healthy",
    "confident", "impressed", "athletic", "fast", "strong", "win", "winning", "hope",
    "optimistic", "love", "hype", "hyped", "chemistry", "development", "potential",
    "underrated", "upgrade", "improved", "depth", "talent", "promising", "bright future",
    "looks sharp", "steal", "value", "ceiling",
]
NEGATIVE = [
    "bad", "concern", "worried", "disappointing", "slow", "injury", "risky", "overrated",
    "overpay", "limited", "decline", "regression", "aging", "old", "washed", "backup",
    "benched", "frustrating", "inconsistent", "weak", "liability", "problem", "issue",
    "miss", "lose", "losing", "struggling", "questionable", "doubt", "cooked",
]
STRONG_NEGATIVE = [
    "bust", "trash", "terrible", "awful", "disaster", "fraud", "done", "finished",
    "washed up", "waste", "nightmare", "toxic", "cut him", "release him", "tank",
    "tanking", "dumpster fire", "trainwreck", "embarrassing", "pathetic", "worst",
    "horrible", "garbage",
]

TOPIC_KEYWORDS = {
    "Jayden Daniels": ["daniels", "jayden", "jd5", "jd", "qb1"],
    "Offense": ["offense", "offensive", "oc", "play calling", "scoring", "red zone", "passing", "rushing"],
    "Defense": ["defense", "defensive", "dc", "pass rush", "secondary", "sack", "turnover", "coverage"],
    "Draft & Roster": ["draft", "pick", "rookie", "trade", "free agent", "signing", "roster", "cut", "waiver"],
    "Coaching": ["quinn", "coach", "coaching", "staff", "scheme", "play call", "game plan", "peters"],
    "O-Line": ["line", "o-line", "offensive line", "blocking", "protection", "tackle", "guard", "center"],
    "Injuries": ["injury", "injured", "hurt", "ir", "out", "questionable", "doubtful", "hamstring", "knee", "ankle"],
    "Stadium & Culture": ["stadium", "fans", "attendance", "culture", "uniforms", "rebrand", "ownership", "tailgate"],
    "NFC East": ["cowboys", "eagles", "giants", "nfc east", "division", "rivalry", "dallas", "philly"],
    "Season Outlook": ["season", "record", "wins", "playoff", "super bowl", "prediction", "expectations", "over under"],
    "Fantasy Football": ["fantasy", "adp", "draft capital", "sleeper", "waiver", "start sit", "league winner"],
}

FALLBACK_PLAYERS = {
    "daniels": "Jayden Daniels",
    "mclaurin": "Terry McLaurin",
    "ertz": "Zach Ertz",
    "ekeler": "Austin Ekeler",
    "robinson": "Brian Robinson Jr.",
    "wagner": "Bobby Wagner",
    "lattimore": "Marshon Lattimore",
    "payne": "Daron Payne",
    "allen": "Jonathan Allen",
    "cosmi": "Sam Cosmi",
    "quinn": "Dan Quinn",
    "peters": "Adam Peters",
}


def clean_text(value: Any, max_len: int = 240) -> str:
    text = str(value or "").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:max_len]


def wordish_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())[:100]


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except Exception:
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except Exception:
        return default


def load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def fetch_current_roster() -> Dict[str, str]:
    """Fetch current Commanders roster from ESPN public endpoint. Falls back safely."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{TEAM_ID_ESPN}?enable=roster"
    roster = dict(FALLBACK_PLAYERS)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CommandersPulseBot/1.0"})
        with urllib.request.urlopen(req, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
        athletes = data.get("team", {}).get("athletes", []) or data.get("athletes", [])
        for item in athletes:
            name = clean_text(item.get("displayName") or item.get("fullName"), 80)
            if not name or " " not in name:
                continue
            last = name.split()[-1].lower().replace(".", "")
            # Skip highly ambiguous one-word matches unless already useful as curated fallback.
            if len(last) >= 4:
                roster[last] = name
        print(f"Roster loaded: {len(roster)} player/name keys")
    except Exception as exc:
        print(f"Roster fetch failed; using fallback roster: {str(exc)[:120]}")
    return roster


def normalize_post(post: Any) -> Optional[Dict[str, Any]]:
    if not post or not isinstance(post, dict):
        return None
    title = clean_text(post.get("title"), 220)
    if not title:
        return None

    permalink = post.get("permalink", "") or ""
    url = post.get("url", "") or ""
    if permalink and not str(permalink).startswith("http"):
        permalink = f"https://reddit.com{permalink}"

    return {
        "title": title,
        "selftext": clean_text(post.get("selftext") or post.get("body"), SELFTEXT_MAX),
        "score": safe_int(post.get("score")),
        "comments": safe_int(post.get("num_comments") or post.get("comments")),
        "created": safe_float(post.get("created_utc") or post.get("created")),
        "url": permalink or url,
        "subreddit": clean_text(post.get("subreddit"), 60),
        "flair": clean_text(post.get("link_flair_text") or post.get("flair"), 80),
    }


def deduplicate(posts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique = []
    for post in posts:
        key = wordish_key(post.get("title", ""))
        if key and key not in seen:
            seen.add(key)
            unique.append(post)
    return unique


def score_post_text(text: str) -> int:
    lowered = f" {text.lower()} "
    score = 0
    for word in STRONG_POSITIVE:
        if word in lowered:
            score += 3
    for word in POSITIVE:
        if word in lowered:
            score += 1
    for word in NEGATIVE:
        if word in lowered:
            score -= 1
    for word in STRONG_NEGATIVE:
        if word in lowered:
            score -= 3

    # Context fixes for common sports slang ambiguity.
    if " fire " in lowered and not re.search(r"fire\s+(the\s+)?(coach|gm|coordinator|quinn|peters|staff)", lowered):
        score += 1
    if re.search(r"fire\s+(the\s+)?(coach|gm|coordinator|quinn|peters|staff)", lowered):
        score -= 3
    if " not bad " in lowered:
        score += 1
    if " not good " in lowered:
        score -= 1
    return score


def analyze_sentiment(posts: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not posts:
        return {
            "score": 0,
            "label": "No data",
            "posts_analyzed": 0,
            "highlights_positive": [],
            "highlights_negative": [],
        }

    total_score = 0.0
    total_weight = 0.0
    highlights_pos = []
    highlights_neg = []

    for post in posts:
        text = f"{post.get('title', '')} {post.get('selftext', '')}"
        ps = score_post_text(text)
        engagement = max(1.0, (abs(post.get("score", 0)) + post.get("comments", 0) + 1) ** 0.5)
        total_score += ps * engagement
        total_weight += engagement

        highlight = {
            "title": post.get("title", "")[:140],
            "score": post.get("score", 0),
            "comments": post.get("comments", 0),
            "url": post.get("url", ""),
        }
        if ps >= 3 and post.get("score", 0) >= 2:
            highlights_pos.append(highlight)
        if ps <= -3 and post.get("score", 0) >= 2:
            highlights_neg.append(highlight)

    raw = total_score / max(0.01, total_weight) * 10
    clamped = max(-100, min(100, round(raw)))

    if clamped >= 50:
        label = "EXTREMELY FIRED UP"
    elif clamped >= 25:
        label = "OPTIMISTIC"
    elif clamped >= 10:
        label = "CAUTIOUSLY HOPEFUL"
    elif clamped >= -10:
        label = "MIXED"
    elif clamped >= -25:
        label = "CONCERNED"
    elif clamped >= -50:
        label = "FRUSTRATED"
    else:
        label = "IN SHAMBLES"

    return {
        "score": clamped,
        "label": label,
        "posts_analyzed": len(posts),
        "highlights_positive": sorted(highlights_pos, key=lambda x: -(x["score"] + x["comments"]))[:5],
        "highlights_negative": sorted(highlights_neg, key=lambda x: -(x["score"] + x["comments"]))[:5],
    }


def detect_hot_topics(posts: List[Dict[str, Any]], min_posts: int = 2) -> List[Dict[str, Any]]:
    topic_scores: Dict[str, int] = {}
    topic_posts: Dict[str, list] = defaultdict(list)

    for post in posts:
        text = f"{post.get('title', '')} {post.get('selftext', '')}".lower()
        for topic, keywords in TOPIC_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                engagement = safe_int(post.get("score")) + safe_int(post.get("comments"))
                topic_scores[topic] = topic_scores.get(topic, 0) + engagement + 10
                topic_posts[topic].append({
                    "title": post.get("title", "")[:140],
                    "score": post.get("score", 0),
                    "comments": post.get("comments", 0),
                    "url": post.get("url", ""),
                })

    hot = []
    for topic, score in sorted(topic_scores.items(), key=lambda item: -item[1]):
        posts_for_topic = topic_posts[topic]
        if len(posts_for_topic) >= min_posts:
            hot.append({
                "topic": topic,
                "buzz_score": score,
                "post_count": len(posts_for_topic),
                "top_posts": sorted(posts_for_topic, key=lambda x: -(x["score"] + x["comments"]))[:3],
            })
    return hot[:8]


def track_player_mentions(posts: List[Dict[str, Any]], roster: Dict[str, str]) -> List[Dict[str, Any]]:
    mentions = defaultdict(lambda: {"count": 0, "sentiment": 0, "posts": []})

    for post in posts:
        text = f"{post.get('title', '')} {post.get('selftext', '')}"
        lowered = text.lower()
        post_score = score_post_text(text)

        for key, full_name in roster.items():
            # Use word boundaries for last names to reduce accidental matches.
            if re.search(rf"\b{re.escape(key.lower())}\b", lowered) or full_name.lower() in lowered:
                item = mentions[full_name]
                item["count"] += 1
                item["sentiment"] += post_score
                if len(item["posts"]) < 3:
                    item["posts"].append({
                        "title": post.get("title", "")[:140],
                        "score": post.get("score", 0),
                        "url": post.get("url", ""),
                    })

    result = []
    for full_name, data in sorted(mentions.items(), key=lambda item: -item[1]["count"]):
        avg_sentiment = round(data["sentiment"] / max(1, data["count"]) * 10)
        result.append({
            "player": full_name,
            "mentions": data["count"],
            "sentiment": max(-100, min(100, avg_sentiment)),
            "top_posts": data["posts"],
        })
    return result[:20]


def generate_pulse_summary(sentiment: Dict[str, Any], hot_topics: List[Dict[str, Any]], player_mentions: List[Dict[str, Any]]) -> str:
    score = sentiment.get("score", 0)
    top_topic = hot_topics[0]["topic"] if hot_topics else "the team"
    top_player = player_mentions[0]["player"] if player_mentions else None

    if score >= 40:
        summary = f"The fan base is buzzing, with {top_topic} driving the conversation."
    elif score >= 15:
        summary = f"The mood is leaning positive around {top_topic}."
    elif score >= -15:
        summary = f"Fan conversation is mixed, with {top_topic} drawing the most debate."
    elif score >= -40:
        summary = f"Fans are restless, and concerns around {top_topic} are showing up."
    else:
        summary = f"Frustration is high, with {top_topic} taking the most heat."

    if top_player:
        summary += f" {top_player.split()[-1]} is one of the loudest player buzz signals."
    return summary


def scrape_subreddit(config: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    posts: List[Dict[str, Any]] = []
    errors: List[str] = []

    for category in config.get("fetch_categories", []):
        try:
            raw = miner.fetch_subreddit_posts(
                config["subreddit"],
                limit=config.get("fetch_limit", 25),
                category=category,
                time_filter="week" if category == "top" else "all",
            )
            for item in raw or []:
                normalized = normalize_post(item)
                if normalized:
                    normalized["source_category"] = category
                    posts.append(normalized)
            print(f"    {category}: {len(raw or [])} posts")
        except Exception as exc:
            message = f"{category}: {str(exc)[:160]}"
            errors.append(message)
            print(f"    {category}: FAILED — {str(exc)[:80]}")
        time.sleep(DELAY_BETWEEN_REQUESTS)

    for query in config.get("search_queries", []):
        try:
            raw = miner.search_reddit(query, limit=config.get("search_limit", 10))
            for item in raw or []:
                normalized = normalize_post(item)
                if not normalized:
                    continue
                subreddit = (normalized.get("subreddit") or "").lower()
                target = config["subreddit"].lower()
                if subreddit == target or config["key"] in {"nfl_commanders", "fantasy_commanders"}:
                    normalized["source_category"] = f"search:{query}"
                    posts.append(normalized)
            print(f"    search '{query}': {len(raw or [])} results")
        except Exception as exc:
            message = f"search '{query}': {str(exc)[:160]}"
            errors.append(message)
            print(f"    search '{query}': FAILED — {str(exc)[:80]}")
        time.sleep(DELAY_BETWEEN_REQUESTS)

    return deduplicate(posts), errors


def update_history(output: Dict[str, Any]) -> Dict[str, Any]:
    history = load_json(HISTORY_PATH, [])
    if not isinstance(history, list):
        history = []

    history.append({
        "updated": output.get("updated"),
        "updated_iso": output.get("updated_iso"),
        "score": output.get("pulse", {}).get("score"),
        "label": output.get("pulse", {}).get("label"),
        "posts_collected": output.get("posts_collected"),
        "top_topic": output.get("hot_topics", [{}])[0].get("topic") if output.get("hot_topics") else None,
    })
    history = history[-60:]
    write_json(HISTORY_PATH, history)
    output["history"] = history[-14:]
    return output


def build_failure_output(errors: Dict[str, Any]) -> Dict[str, Any]:
    previous = load_json(OUTPUT_PATH, {})
    now = time.time()
    return {
        "team": "WAS",
        "team_name": "Washington Commanders",
        "source_label": "Community Pulse",
        "updated": previous.get("updated"),
        "updated_iso": previous.get("updated_iso"),
        "last_attempted_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "posts_collected": previous.get("posts_collected", 0),
        "pulse": {
            **previous.get("pulse", {}),
            "stale": True,
            "summary": previous.get("pulse", {}).get("summary") or "Community Pulse data is temporarily unavailable.",
        },
        "sentiment": previous.get("sentiment", {}),
        "hot_topics": previous.get("hot_topics", []),
        "player_mentions": previous.get("player_mentions", []),
        "highlights": previous.get("highlights", {"positive": [], "negative": []}),
        "recent_posts": previous.get("recent_posts", []),
        "errors": errors,
        "meta": {
            "privacy_note": "Only public post metadata/titles and derived buzz scores are saved. Usernames and long selftext are intentionally omitted.",
            "manual_fallback_available": True,
        },
    }


def main() -> None:
    print("=" * 64)
    print("COMMANDERS PULSE BUILDER")
    print("=" * 64)

    previous = load_json(OUTPUT_PATH, {})
    previous_score = previous.get("pulse", {}).get("score") if isinstance(previous, dict) else None
    roster = fetch_current_roster()

    all_posts: List[Dict[str, Any]] = []
    all_errors: Dict[str, Any] = {}

    for config in SUBS_TO_SCAN:
        print(f"\nScanning r/{config['subreddit']} ({config['key']})...")
        posts, errors = scrape_subreddit(config)
        all_posts.extend(posts)
        if errors:
            all_errors[config["key"]] = errors
        print(f"  → {len(posts)} posts collected")

    all_posts = deduplicate(all_posts)
    print(f"\nTotal unique posts: {len(all_posts)}")

    if not all_posts:
        output = build_failure_output({**all_errors, "fatal": "No posts collected"})
        write_json(OUTPUT_PATH, output)
        print(f"No posts collected. Wrote fallback output to {OUTPUT_PATH}")
        return

    sentiment = analyze_sentiment(all_posts)
    hot_topics = detect_hot_topics(all_posts)
    player_mentions = track_player_mentions(all_posts, roster)
    summary = generate_pulse_summary(sentiment, hot_topics, player_mentions)

    now = time.time()
    score = sentiment["score"]
    score_delta = score - previous_score if isinstance(previous_score, int) else None

    output = {
        "team": "WAS",
        "team_name": "Washington Commanders",
        "source_label": "Community Pulse",
        "updated": now,
        "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "posts_collected": len(all_posts),
        "pulse": {
            "score": score,
            "label": sentiment["label"],
            "summary": summary,
            "posts_analyzed": sentiment["posts_analyzed"],
            "previous_score": previous_score,
            "score_delta": score_delta,
            "stale": False,
            "stale_after_hours": STALE_AFTER_HOURS,
        },
        "sentiment": sentiment,
        "hot_topics": hot_topics,
        "player_mentions": player_mentions,
        "highlights": {
            "positive": sentiment["highlights_positive"],
            "negative": sentiment["highlights_negative"],
        },
        "recent_posts": sorted(all_posts, key=lambda item: -safe_float(item.get("created")))[:50],
        "errors": all_errors,
        "meta": {
            "privacy_note": "Only public post metadata/titles and derived buzz scores are saved. Usernames and long selftext are intentionally omitted.",
            "manual_fallback_available": True,
            "signal_note": "This is a fan conversation signal, not an official team report or factual player evaluation.",
        },
    }

    output = update_history(output)
    write_json(OUTPUT_PATH, output)

    print(f"\nDone. Wrote {OUTPUT_PATH}")
    print(f"Pulse: {score:+d} — {sentiment['label']}")
    if score_delta is not None:
        print(f"Change since last scrape: {score_delta:+d}")
    if hot_topics:
        print(f"Top topic: {hot_topics[0]['topic']} ({hot_topics[0]['post_count']} posts)")
    if player_mentions:
        print(f"Most discussed: {player_mentions[0]['player']} ({player_mentions[0]['mentions']} mentions)")


if __name__ == "__main__":
    main()
