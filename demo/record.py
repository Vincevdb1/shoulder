#!/usr/bin/env python3
"""Record the shoulder demo video.

The script builds shoulder and makes a throwaway git project with a long
snake.js. It starts shoulder in a tmux server of its own and writes Claude
Code and Codex session logs on a timeline. Claude reads snake.js and
simplifies it one line at a time. Codex adds tests in the same project. The
script captures the screen, renders each frame and encodes an MP4 for X.

The session logs go to a temporary directory through CLAUDE_CONFIG_DIR and
CODEX_HOME. The script does not read or change your real sessions.

The terminal gets the colors of the original design, so the video looks like
the design. shoulder reads these colors from the terminal like any theme.

Requirements: go, git, node, tmux, ffmpeg, the JetBrains Mono Nerd Font, and
Python with Pillow and fontTools.

    python3 -m venv .venv && .venv/bin/pip install pillow fonttools
    .venv/bin/python demo/record.py

The video goes to site/shoulder-demo.mp4, which the website and the release use.
"""

import argparse
import datetime
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SOCK = "shoulder-demo"
COLS, ROWS = 160, 40
CW, CH = 11, 24  # cell size in pixels
VW, VH = 1920, 1080
FPS = 30
FONTS = "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-%s.ttf"
FALLBACK = "/usr/share/fonts/Adwaita/AdwaitaMono-Regular.ttf"


def oklch(L, C, h):
    """Convert an OKLCH color of the design to sRGB."""
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    lin = (
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )

    def gamma(x):
        x = min(1.0, max(0.0, x))
        return 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055

    return tuple(round(gamma(x) * 255) for x in lin)


# The palette of the design, as terminal colors.
FG = oklch(0.88, 0.015, 80)
BG = oklch(0.2, 0.008, 75)
PAGE = oklch(0.13, 0.006, 75)
FRAME = oklch(0.3, 0.01, 75)
PALETTE = [
    oklch(0.16, 0.007, 75),  # black
    oklch(0.66, 0.17, 25),  # red: deleted lines
    oklch(0.72, 0.14, 145),  # green: added lines
    oklch(0.8, 0.13, 55),  # yellow: the first agent
    oklch(0.72, 0.12, 245),  # blue: changed lines
    oklch(0.8, 0.13, 300),  # magenta: the second agent
    oklch(0.8, 0.13, 195),  # cyan
    oklch(0.74, 0.015, 78),  # white
    oklch(0.46, 0.012, 78),  # bright black: faint text
    oklch(0.76, 0.11, 30),
    oklch(0.77, 0.1, 130),
    oklch(0.8, 0.1, 85),
    oklch(0.78, 0.1, 245),
    oklch(0.76, 0.11, 330),
    oklch(0.77, 0.09, 195),
    FG,
]


def hexc(c):
    return "#%02x%02x%02x" % c


SNAKE = r"""#!/usr/bin/env node
// snake.js is the game of snake. The game logic is a set of pure functions
// that return a new game on each move. A small terminal front end plays it.
'use strict';

const DIRS = {
  up: { x: 0, y: -1 },
  down: { x: 0, y: 1 },
  left: { x: -1, y: 0 },
  right: { x: 1, y: 0 },
};
const OPPOSITE = { up: 'down', down: 'up', left: 'right', right: 'left' };
const MAX_QUEUE = 2;

/** createGame returns a new game with the snake in the middle, moving right. */
function createGame({ width = 20, height = 15, length = 3, random = Math.random } = {}) {
  if (width < length + 2 || height < 3) {
    throw new Error('the board is too small for the snake');
  }
  const cx = Math.floor(width / 2);
  const cy = Math.floor(height / 2);
  const snake = Array.from({ length }, (_, i) => ({ x: cx - i, y: cy }));
  const game = { width, height, snake, dir: 'right', queue: [], food: null, score: 0, over: false, won: false, random };
  return { ...game, food: placeFood(game) };
}

const same = (a, b) => a.x === b.x && a.y === b.y;

/** placeFood picks a random free cell. It returns null when the snake fills the board. */
function placeFood(game) {
  const taken = new Set(game.snake.map((c) => c.y * game.width + c.x));
  const free = [];
  for (let i = 0; i < game.width * game.height; i++) {
    if (!taken.has(i)) free.push({ x: i % game.width, y: Math.floor(i / game.width) });
  }
  return free.length ? free[Math.floor(game.random() * free.length)] : null;
}

/**
 * turn queues a change of direction. It ignores a turn into the opposite
 * direction, because the snake would run into its own neck. The queue keeps
 * two fast key presses between two steps, so a quick U-turn works.
 */
function turn(game, dir) {
  const last = game.queue.length ? game.queue[game.queue.length - 1] : game.dir;
  if (game.over || !DIRS[dir] || dir === last || dir === OPPOSITE[last] || game.queue.length >= MAX_QUEUE) {
    return game;
  }
  return { ...game, queue: [...game.queue, dir] };
}

/** step moves the snake one cell and returns the new game. */
function step(game) {
  if (game.over) return game;
  const [dir, ...queue] = game.queue.length ? game.queue : [game.dir];
  const head = game.snake[0];
  const next = { x: head.x + DIRS[dir].x, y: head.y + DIRS[dir].y };
  const eats = game.food !== null && same(next, game.food);
  // The tail leaves its cell in this step unless the snake grows, so the
  // head can move into the cell where the tail is now.
  const body = eats ? game.snake : game.snake.slice(0, -1);
  const hitsWall = next.x < 0 || next.y < 0 || next.x >= game.width || next.y >= game.height;
  if (hitsWall || body.some((c) => same(c, next))) {
    return { ...game, dir, queue, over: true };
  }
  const moved = { ...game, dir, queue, snake: [next, ...body] };
  if (!eats) return moved;
  const food = placeFood(moved);
  return { ...moved, food, score: game.score + 1, over: food === null, won: food === null };
}

/** tickMs is the time between two steps. The snake gets faster as it grows. */
const tickMs = (game) => Math.max(60, 140 - game.score * 4);

const CSI = '\x1b[';
const paint = (sgr, text) => `${CSI}${sgr}m${text}${CSI}0m`;

/** render draws the board with ANSI colors, so it follows the terminal theme. */
function render(game) {
  const cells = new Map(game.snake.map((c, i) => [c.y * game.width + c.x, i === 0 ? 'head' : 'body']));
  const lines = [];
  for (let y = 0; y < game.height; y++) {
    let row = '';
    for (let x = 0; x < game.width; x++) {
      const kind = cells.get(y * game.width + x);
      if (kind === 'head') row += paint(102, '  ');
      else if (kind === 'body') row += paint(42, '  ');
      else if (game.food && game.food.x === x && game.food.y === y) row += paint(31, '●') + ' ';
      else row += '  ';
    }
    lines.push(row);
  }
  return CSI + 'H' + lines.join('\n');
}

function run() {
  const { stdin, stdout } = process;
  let game = createGame();
  const restore = () => stdout.write(CSI + '?25h' + CSI + '?1049l');
  process.on('exit', restore);
  stdout.write(CSI + '?1049h' + CSI + '?25l');
  stdin.setRawMode(true);
  stdin.on('data', (key) => {
    if (key.toString() === 'q') process.exit(0);
  });
  setInterval(() => {
    game = step(game);
    stdout.write(render(game));
  }, tickMs(game));
}

module.exports = { DIRS, createGame, placeFood, turn, step, tickMs };

if (require.main === module) run();
"""

TESTS = """const test = require('node:test');
const assert = require('node:assert');
const { createGame, turn, step } = require('./snake.js');

const fixed = () => 0;

test('the snake moves one cell per step', () => {
  const game = step(createGame({ width: 10, height: 5, random: fixed }));
  assert.deepStrictEqual(game.snake[0], { x: 6, y: 2 });
});

test('the snake grows when it eats', () => {
  const game = createGame({ width: 10, height: 5, random: fixed });
  const next = step({ ...game, food: { x: 6, y: 2 } });
  assert.strictEqual(next.score, 1);
  assert.strictEqual(next.snake.length, 4);
});

test('a U-turn is ignored', () => {
  const game = createGame({ width: 10, height: 5, random: fixed });
  assert.strictEqual(turn(game, 'left'), game);
});

test('the wall ends the game', () => {
  let game = createGame({ width: 6, height: 3, random: fixed });
  while (!game.over) game = step(game);
  assert.ok(game.over);
});
"""

README = "# arcade\n\nSmall terminal games.\n"

# The edits that Claude makes, one line each. A target is the exact text of
# a line, or ("after", prefix) for the line after the line with that prefix,
# or ("before", prefix) for the line before it.
EDITS = [
    ("del", "    throw new Error('the board is too small for the snake');", None),
    ("set", "  if (width < length + 2 || height < 3) {",
     "  if (width < length + 2 || height < 3) throw new Error('the board is too small for the snake');"),
    ("del", ("after", "  if (width < length + 2 || height < 3) throw"), None),
    ("set", "  const snake = Array.from({ length }, (_, i) => ({ x: cx - i, y: cy }));",
     "  const snake = Array.from({ length }, (_, i) => ({ x: Math.floor(width / 2) - i, y: Math.floor(height / 2) }));"),
    ("del", "  const cx = Math.floor(width / 2);", None),
    ("del", "  const cy = Math.floor(height / 2);", None),
    ("set", "  const free = [];",
     "  const free = [...Array(game.width * game.height).keys()].filter((i) => !taken.has(i))"
     ".map((i) => ({ x: i % game.width, y: Math.floor(i / game.width) }));"),
    ("del", "    if (!taken.has(i)) free.push({ x: i % game.width, y: Math.floor(i / game.width) });", None),
    ("del", "  for (let i = 0; i < game.width * game.height; i++) {", None),
    ("del", ("before", "  return free.length ?"), None),
    ("set", " * turn queues a change of direction. It ignores a turn into the opposite",
     " * turn queues a change of direction. It ignores a U-turn and keeps two fast key presses."),
    ("del", " * direction, because the snake would run into its own neck. The queue keeps", None),
    ("del", " * two fast key presses between two steps, so a quick U-turn works.", None),
    ("set", "  // The tail leaves its cell in this step unless the snake grows, so the",
     "  // Unless the snake grows, the tail moves away, so the head may enter its cell."),
    ("del", "  // head can move into the cell where the tail is now.", None),
    ("set", "      else if (game.food && game.food.x === x && game.food.y === y) row += paint(31, '●') + ' ';",
     "      else if (game.food && same(game.food, { x, y })) row += paint(31, '●') + ' ';"),
    ("set", "  process.on('exit', restore);",
     "  process.on('exit', () => stdout.write(CSI + '?25h' + CSI + '?1049l'));"),
    ("del", "  const restore = () => stdout.write(CSI + '?25h' + CSI + '?1049l');", None),
]


def iso():
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def append(path, obj):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")


class Snake:
    """The snake.js file of the demo project, edited one line at a time."""

    def __init__(self, root):
        self.path = os.path.join(root, "snake.js")
        self.lines = SNAKE.split("\n")

    def find(self, target):
        if isinstance(target, tuple):
            where, prefix = target
            i = next(i for i, l in enumerate(self.lines) if l.startswith(prefix))
            return i + 1 if where == "after" else i - 1
        return self.lines.index(target)

    def apply(self, op, target, new):
        i = self.find(target)
        old = self.lines[i]
        if op == "del":
            del self.lines[i]
        else:
            self.lines[i] = new
        self.save()
        return i, old, new or ""

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines))


class ClaudeLog:
    """Writes a Claude Code transcript in the format of ~/.claude/projects."""

    def __init__(self, cfg, root):
        self.root, self.sid, self.ctx, self.n = root, str(uuid.uuid4()), 21000, 0
        d = os.path.join(cfg, "projects", re.sub(r"[^A-Za-z0-9]", "-", root))
        os.makedirs(d, exist_ok=True)
        self.path = os.path.join(d, self.sid + ".jsonl")

    def write(self, **obj):
        obj.setdefault("timestamp", iso())
        obj.update(cwd=self.root, sessionId=self.sid, uuid=str(uuid.uuid4()))
        append(self.path, obj)

    def assistant(self, blocks, stop):
        self.ctx += 900
        self.write(type="assistant", message={
            "role": "assistant", "model": "claude-opus-5-5", "content": blocks, "stop_reason": stop,
            "usage": {"input_tokens": 3, "cache_read_input_tokens": self.ctx, "cache_creation_input_tokens": 400},
        })

    def say(self, text, end=False):
        self.assistant([{"type": "text", "text": text}], "end_turn" if end else None)

    def tool(self, name, inp):
        self.n += 1
        tid = "toolu_demo%04d" % self.n
        self.assistant([{"type": "tool_use", "id": tid, "name": name, "input": inp}], "tool_use")
        return tid

    def result(self, tid, content, tur, error=False):
        self.write(type="user", toolUseResult=tur, message={"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": content, "is_error": error}]})


class CodexLog:
    """Writes a Codex rollout in the format of ~/.codex/sessions."""

    def __init__(self, home, root):
        now = datetime.datetime.now()
        d = os.path.join(home, "sessions", now.strftime("%Y/%m/%d"))
        os.makedirs(d, exist_ok=True)
        self.root, self.id, self.n = root, str(uuid.uuid4()), 0
        self.path = os.path.join(d, "rollout-%s-%s.jsonl" % (now.strftime("%Y-%m-%dT%H-%M-%S"), self.id))

    def write(self, kind, payload):
        append(self.path, {"timestamp": iso(), "type": kind, "payload": payload})

    def call_id(self):
        self.n += 1
        return "call_demo%d" % self.n

    def meta(self):
        self.write("session_meta", {"id": self.id, "timestamp": iso(), "cwd": self.root,
                                    "originator": "codex_cli_rs", "cli_version": "0.130.0"})

    def prompt(self, text):
        self.write("event_msg", {"type": "task_started", "turn_id": "1"})
        self.write("event_msg", {"type": "user_message", "message": text})

    def patch(self, text):
        cid = self.call_id()
        self.write("response_item", {"type": "custom_tool_call", "status": "completed",
                                     "call_id": cid, "name": "apply_patch", "input": text})
        return cid

    def run(self, cmd):
        cid = self.call_id()
        self.write("response_item", {"type": "function_call", "name": "exec_command", "call_id": cid,
                                     "arguments": json.dumps({"cmd": cmd, "workdir": self.root})})
        return cid

    def output(self, cid, text):
        self.write("response_item", {"type": "function_call_output", "call_id": cid, "output": text})

    def tokens(self, n):
        self.write("event_msg", {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": n}, "model_context_window": 258400}})

    def say(self, text):
        self.write("response_item", {"type": "message", "role": "assistant",
                                     "content": [{"type": "output_text", "text": text}]})

    def done(self, text):
        self.write("event_msg", {"type": "task_complete", "turn_id": "1", "last_agent_message": text})


def sh(*cmd, cwd=None, env=None):
    return subprocess.run(cmd, cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


def tmux(*args):
    return subprocess.run(["tmux", "-L", SOCK, *args], capture_output=True, text=True).stdout


def node_tests(root):
    out = subprocess.run(["node", "--test", "--test-reporter=spec", "snake.test.js"],
                         cwd=root, capture_output=True, text=True)
    text = re.sub(r"\x1b\[[0-9;]*m", "", out.stdout).rstrip()
    if out.returncode != 0:
        raise SystemExit("the tests fail:\n" + text + out.stderr)
    return text


class Recorder:
    """Captures the tmux pane each time it changes."""

    def __init__(self):
        self.frames, self.stop, self.t0 = [], threading.Event(), None

    def start(self):
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def loop(self):
        last = None
        while not self.stop.is_set():
            out = tmux("capture-pane", "-p", "-e", "-N", "-t", "demo")
            if self.t0 is None and "AGENTS" in out:
                self.t0 = time.monotonic()
            if self.t0 is not None and out != last:
                self.frames.append((time.monotonic() - self.t0, out))
                last = out
            time.sleep(1 / 60)

    def finish(self):
        self.stop.set()
        self.thread.join()


class Painter:
    """Renders a tmux capture with escape codes to an image."""

    SGR = re.compile(r"\x1b\[([0-9;:]*)m|([^\x1b])", re.S)

    def __init__(self):
        self.fonts = {k: ImageFont.truetype(FONTS % v, 18) for k, v in
                      {(0, 0): "Regular", (1, 0): "Bold", (0, 1): "Italic", (1, 1): "BoldItalic"}.items()}
        self.cmap = TTFont(FONTS % "Regular").getBestCmap()
        self.fallback = ImageFont.truetype(FALLBACK, 18)

    def color(self, ps, i):
        if ps[i + 1] == 5:
            n = ps[i + 2]
            if n < 16:
                return PALETTE[n], 3
            if n < 232:
                n -= 16
                lv = [0, 95, 135, 175, 215, 255]
                return (lv[n // 36], lv[n // 6 % 6], lv[n % 6]), 3
            v = 8 + (n - 232) * 10
            return (v, v, v), 3
        return tuple(ps[i + 2:i + 5]), 5

    def paint(self, text):
        img = Image.new("RGB", (COLS * CW, ROWS * CH), BG)
        d = ImageDraw.Draw(img)
        for y, line in enumerate(text.split("\n")[:ROWS]):
            fg = bg = None
            bold = ital = rev = faint = strike = False
            x = 0
            for m in self.SGR.finditer(line):
                if m.group(1) is not None:
                    ps = [int(p) if p else 0 for p in re.split("[;:]", m.group(1))] or [0]
                    i = 0
                    while i < len(ps):
                        p = ps[i]
                        if p == 0:
                            fg = bg = None
                            bold = ital = rev = faint = strike = False
                        elif p == 1:
                            bold = True
                        elif p == 2:
                            faint = True
                        elif p == 3:
                            ital = True
                        elif p == 7:
                            rev = True
                        elif p == 9:
                            strike = True
                        elif p == 22:
                            bold = faint = False
                        elif p == 23:
                            ital = False
                        elif p == 27:
                            rev = False
                        elif p == 29:
                            strike = False
                        elif 30 <= p <= 37:
                            fg = PALETTE[p - 30]
                        elif 90 <= p <= 97:
                            fg = PALETTE[p - 82]
                        elif 40 <= p <= 47:
                            bg = PALETTE[p - 40]
                        elif 100 <= p <= 107:
                            bg = PALETTE[p - 92]
                        elif p == 39:
                            fg = None
                        elif p == 49:
                            bg = None
                        elif p in (38, 48) and i + 1 < len(ps):
                            c, used = self.color(ps, i)
                            if p == 38:
                                fg = c
                            else:
                                bg = c
                            i += used - 1
                        i += 1
                    continue
                if x >= COLS:
                    break
                ch = m.group(2)
                f, b = fg or FG, bg or BG
                if rev:
                    f, b = b, f
                if faint:
                    f = tuple((u + v) // 2 for u, v in zip(f, b))
                self.cell(d, x, y, ch, f, b, bold, ital, strike)
                x += 1
        return img

    def cell(self, d, x, y, ch, f, b, bold, ital, strike):
        px, py = x * CW, y * CH
        d.rectangle([px, py, px + CW - 1, py + CH - 1], fill=b)
        mid_x, mid_y = px + CW // 2, py + CH // 2
        if ch == " ":
            pass
        elif ch == "█":
            d.rectangle([px, py, px + CW - 1, py + CH - 1], fill=f)
        elif ch == "▎":
            d.rectangle([px, py, px + 2, py + CH - 1], fill=f)
        elif ch == "▁":
            d.rectangle([px, py + CH - 3, px + CW - 1, py + CH - 1], fill=f)
        elif ch == "▔":
            d.rectangle([px, py, px + CW - 1, py + 2], fill=f)
        elif ch == "│":
            d.line([mid_x, py, mid_x, py + CH - 1], fill=f)
        elif ch == "─":
            d.line([px, mid_y, px + CW - 1, mid_y], fill=f)
        elif ch == "━":
            d.rectangle([px, mid_y - 1, px + CW - 1, mid_y + 1], fill=f)
        elif ch in "┌┐└┘":
            hx = (mid_x, px + CW - 1) if ch in "┌└" else (px, mid_x)
            vy = (mid_y, py + CH - 1) if ch in "┌┐" else (py, mid_y)
            d.line([hx[0], mid_y, hx[1], mid_y], fill=f)
            d.line([mid_x, vy[0], mid_x, vy[1]], fill=f)
        else:
            font = self.fonts[(int(bold), int(ital))] if ord(ch) in self.cmap else self.fallback
            d.text((px, py + 18), ch, font=font, fill=f, anchor="ls")
        if strike:
            d.line([px, mid_y, px + CW - 1, mid_y], fill=f)


class Composer:
    """Puts a terminal image in a window on the page, with a caption."""

    def __init__(self):
        self.tw, self.th = COLS * CW, ROWS * CH
        self.x, self.y = (VW - self.tw) // 2, 28
        page = Image.new("RGB", (VW, VH), PAGE)
        shadow = Image.new("L", (VW, VH), 0)
        ImageDraw.Draw(shadow).rounded_rectangle(
            [self.x, self.y + 18, self.x + self.tw, self.y + self.th + 18], 14, fill=120)
        shadow = shadow.filter(ImageFilter.GaussianBlur(24))
        page.paste(Image.new("RGB", (VW, VH), (0, 0, 0)), (0, 0), shadow)
        self.page = page
        self.mask = Image.new("L", (self.tw, self.th), 0)
        ImageDraw.Draw(self.mask).rounded_rectangle([0, 0, self.tw - 1, self.th - 1], 8, fill=255)
        self.caption_font = ImageFont.truetype(FONTS % "Regular", 26)
        self.brand_font = ImageFont.truetype(FONTS % "Bold", 26)

    def compose(self, term, caption):
        img = self.page.copy()
        img.paste(term, (self.x, self.y), self.mask)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([self.x - 1, self.y - 1, self.x + self.tw, self.y + self.th], 9, outline=FRAME)
        cy = self.y + self.th + (VH - self.y - self.th) // 2 + 2
        brand = "shoulder"
        bw = d.textlength(brand + "   ", font=self.brand_font)
        cw = d.textlength(caption, font=self.caption_font) if caption else 0
        left = (VW - bw - cw) / 2
        d.text((left, cy), brand, font=self.brand_font, fill=PALETTE[3], anchor="lm")
        if caption:
            d.text((left + bw, cy), caption, font=self.caption_font, fill=FG, anchor="lm")
        return img


def main():
    ap = argparse.ArgumentParser(description="Record the shoulder demo video.")
    ap.add_argument("--out", default=os.path.join(REPO, "site", "shoulder-demo.mp4"))
    ap.add_argument("--work", help="work directory; a new temporary directory by default")
    args = ap.parse_args()

    for tool in ("go", "git", "node", "tmux", "ffmpeg"):
        if not shutil.which(tool):
            raise SystemExit(tool + " is necessary")
    work = os.path.abspath(args.work or tempfile.mkdtemp(prefix="shoulder-demo-"))
    root = os.path.join(work, "arcade")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(root)

    print("making the demo project in", root)
    snake = Snake(root)
    snake.save()
    with open(os.path.join(root, "README.md"), "w") as f:
        f.write(README)
    git = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com"]
    sh("git", "init", "-q", "-b", "main", cwd=root)
    sh(*git, "add", ".", cwd=root)
    sh(*git, "commit", "-q", "-m", "Add snake", cwd=root)

    # The tests must pass on the old and on the simplified snake.js.
    tests = os.path.join(root, "snake.test.js")
    with open(tests, "w") as f:
        f.write(TESTS)
    test_out = node_tests(root)
    check = Snake(root)
    for op, target, new in EDITS:
        check.apply(op, target, new)
    node_tests(root)
    os.remove(tests)
    snake.save()

    print("building shoulder")
    binary = os.path.join(work, "shoulder")
    sh("go", "build", "-o", binary, ".", cwd=REPO)

    homes = {k: os.path.join(work, k) for k in ("claude", "codex", "gemini", "xdg")}
    for d in homes.values():
        os.makedirs(d, exist_ok=True)
    claude = ClaudeLog(homes["claude"], root)
    claude.write(type="permission-mode", permissionMode="default")
    claude.write(type="user", message={"role": "user", "content": "Simplify snake.js. Edit one line at a time."})
    claude.write(type="ai-title", aiTitle="Simplify snake.js")
    codex = CodexLog(homes["codex"], root)
    codex.meta()

    conf = os.path.join(work, "tmux.conf")
    with open(conf, "w") as f:
        f.write("set -g status off\nset -g escape-time 0\n")
        f.write('set -g window-style "fg=%s,bg=%s"\n' % (hexc(FG), hexc(BG)))
        for i, c in enumerate(PALETTE):
            f.write('set -g pane-colours[%d] "%s"\n' % (i, hexc(c)))
    env = " ".join([
        "TERM=xterm-256color", "COLORTERM=truecolor",
        "CLAUDE_CONFIG_DIR=" + homes["claude"], "CODEX_HOME=" + homes["codex"],
        "GEMINI_CLI_HOME=" + homes["gemini"], "XDG_DATA_HOME=" + homes["xdg"],
    ])
    tmux("kill-server")
    subprocess.run(["tmux", "-L", SOCK, "-f", conf, "new-session", "-d", "-s", "demo",
                    "-x", str(COLS), "-y", str(ROWS), "env %s %s --since 1h %s" % (env, binary, root)], check=True)

    rec = Recorder()
    rec.start()
    while rec.t0 is None:
        time.sleep(0.01)
    captions = []

    def at(t):
        time.sleep(max(0.0, rec.t0 + t - time.monotonic()))

    def caption(t, text):
        at(t)
        captions.append((t, text))

    def key(t, *keys):
        at(t)
        for k in keys:
            tmux("send-keys", "-t", "demo", "-l", k)
            time.sleep(0.08)

    def edit(t, n):
        at(t)
        op, target, new = EDITS[n]
        i, old, new = snake.apply(op, target, new)
        hunk = {"oldStart": i + 1, "oldLines": 1, "newStart": i + 1, "newLines": 0 if op == "del" else 1,
                "lines": ["-" + old] + ([] if op == "del" else ["+" + new])}
        tid = claude.tool("Edit", {"file_path": snake.path, "old_string": old, "new_string": new})
        claude.result(tid, "The file %s has been updated successfully." % snake.path, {
            "filePath": snake.path, "oldString": old, "newString": new,
            "structuredPatch": [hunk], "userModified": False, "replaceAll": False})

    print("recording")
    caption(0.0, "watches your coding agents work, live")
    at(1.8)
    claude.say("I will read snake.js first.")
    caption(2.6, "Claude reads snake.js")
    tid = claude.tool("Read", {"file_path": snake.path})
    n = len(snake.lines)
    claude.result(tid, "(file content)", {"type": "text", "file": {
        "filePath": snake.path, "content": "", "numLines": n, "startLine": 1, "totalLines": n}})
    at(5.0)
    claude.say("I will simplify it with small edits, one line at a time.")
    caption(5.4, "then simplifies it, one line at a time")
    t = 6.0
    for k in range(9):
        edit(t, k)
        t += 1.1
        if k == 5:
            at(t - 0.6)
            codex.prompt("Add tests for the snake logic.")
            caption(t - 0.5, "Codex starts on tests in the same project")

    caption(t + 0.4, "a new edit by another agent? the view jumps there")
    at(t + 0.5)
    patch = "*** Begin Patch\n*** Add File: snake.test.js\n" + "".join(
        "+" + l + "\n" for l in TESTS.rstrip("\n").split("\n")) + "*** End Patch"
    cid = codex.patch(patch)
    with open(tests, "w") as f:
        f.write(TESTS)
    codex.write("response_item", {"type": "custom_tool_call_output", "call_id": cid,
                                  "output": "Success. Updated the following files:\nA snake.test.js"})
    codex.tokens(14200)
    at(t + 1.6)
    cid = codex.run("node --test")
    at(t + 2.3)
    codex.output(cid, "Chunk ID: 1\nWall time: 0.3 seconds\nProcess exited with code 0\nOutput:\n" + test_out)
    t += 3.6
    caption(t - 0.2, "and back to the next edit by Claude")
    for k in range(9, len(EDITS)):
        edit(t, k)
        if k == 10:
            codex.say("Four tests cover moves, growth, walls and U-turns. They pass.")
            codex.done("Four tests cover moves, growth, walls and U-turns. They pass.")
        t += 1.1

    caption(t + 0.2, "Claude runs the tests")
    at(t + 0.3)
    tid = claude.tool("Bash", {"command": "node --test", "description": "Run the tests"})
    at(t + 1.1)
    claude.result(tid, node_tests(root), {"stdout": node_tests(root), "stderr": "",
                                          "interrupted": False, "isImage": False})
    at(t + 1.9)
    claude.say("snake.js is 14 lines shorter, and the 4 tests pass.", end=True)
    claude.write(type="system", subtype="turn_duration", durationMs=31000)
    t += 3.2
    caption(t, "]c walks the changes: red is the old line, green is the new one")
    key(t + 0.4, "g", "g")
    key(t + 1.2, "]", "c")
    key(t + 2.4, "]", "c")
    key(t + 3.6, "]", "c")
    t += 5.2
    caption(t, "s shows one split per agent")
    key(t + 0.3, "s")
    t += 4.2
    caption(t, "for Claude Code, Codex, Gemini CLI and opencode, in your terminal theme")
    at(t + 3.4)
    end = t + 3.4
    rec.finish()
    tmux("kill-server")

    print("rendering %d frames" % len(rec.frames))
    render(rec.frames, captions, end, work, args.out)
    print("wrote", args.out)


def render(frames, captions, end, work, out):
    painter, composer = Painter(), Composer()
    times = sorted({t for t, _ in frames if t < end} | {t for t, _ in captions} | {0.0})
    frame_dir = os.path.join(work, "frames")
    os.makedirs(frame_dir, exist_ok=True)
    cache, entries = {}, []
    fi = ci = 0
    for k, t in enumerate(times):
        while fi + 1 < len(frames) and frames[fi + 1][0] <= t:
            fi += 1
        while ci + 1 < len(captions) and captions[ci + 1][0] <= t:
            ci += 1
        screen, cap = frames[fi][1], captions[ci][1] if captions else ""
        key = hashlib.sha1((screen + "\x00" + cap).encode()).hexdigest()
        if key not in cache:
            path = os.path.join(frame_dir, "%05d.png" % len(cache))
            composer.compose(painter.paint(screen), cap).save(path)
            cache[key] = path
        nxt = times[k + 1] if k + 1 < len(times) else end
        entries.append((cache[key], max(1 / FPS, nxt - t)))
    lst = os.path.join(work, "frames.txt")
    with open(lst, "w") as f:
        for path, dur in entries:
            f.write("file '%s'\nduration %.4f\n" % (path, dur))
        f.write("file '%s'\n" % entries[-1][0])
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-vf", "fps=%d,format=yuv420p" % FPS, "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                    "-profile:v", "high", "-level", "4.1", "-movflags", "+faststart", out], check=True)


if __name__ == "__main__":
    main()
