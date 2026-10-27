package ui

import (
	"strconv"
	"strings"

	"github.com/mattn/go-runewidth"
)

// Style is the look of one cell.
type Style struct {
	FG, BG                               Color
	Bold, Italic, Strike, Faint, Reverse bool
}

type cell struct {
	s  string
	w  uint8 // 0 for the second half of a wide character
	st Style
}

// Canvas is a grid of cells that renders to ANSI text.
type Canvas struct {
	W, H  int
	cells []cell
}

func newCanvas(w, h int) *Canvas {
	c := &Canvas{W: w, H: h, cells: make([]cell, w*h)}
	for i := range c.cells {
		c.cells[i] = cell{s: " ", w: 1}
	}
	return c
}

func (c *Canvas) at(x, y int) *cell { return &c.cells[y*c.W+x] }

// fill clears a rectangle and sets its background.
func (c *Canvas) fill(x, y, w, h int, bg Color) {
	for yy := max(0, y); yy < min(c.H, y+h); yy++ {
		for xx := max(0, x); xx < min(c.W, x+w); xx++ {
			*c.at(xx, yy) = cell{s: " ", w: 1, st: Style{BG: bg}}
		}
	}
}

// clear makes cell x a plain space and repairs a wide character that it
// cuts.
func (c *Canvas) clear(x, y int) {
	cl := c.at(x, y)
	if cl.w == 0 && x > 0 {
		p := c.at(x-1, y)
		p.s, p.w = " ", 1
	}
	if cl.w == 2 && x+1 < c.W {
		n := c.at(x+1, y)
		n.s, n.w = " ", 1
	}
	cl.s, cl.w = " ", 1
}

// text writes s from column x and stops before column maxX. A style without
// a background keeps the background of each cell. It returns the column after
// the text.
func (c *Canvas) text(x, y, maxX int, s string, st Style) int {
	if y < 0 || y >= c.H {
		return x
	}
	maxX = min(maxX, c.W)
	for _, r := range s {
		if x >= maxX {
			break
		}
		if r == '\t' || r == '\n' || r == '\r' {
			r = ' '
		}
		if r < 0x20 || r == 0x7f {
			continue
		}
		w := runewidth.RuneWidth(r)
		if w == 0 {
			if x > 0 {
				p := c.at(x-1, y)
				if p.w == 0 && x > 1 {
					p = c.at(x-2, y)
				}
				p.s += string(r)
			}
			continue
		}
		if x+w > maxX {
			for ; x < maxX; x++ {
				c.put(x, y, " ", 1, st)
			}
			break
		}
		c.put(x, y, string(r), uint8(w), st)
		if w == 2 {
			c.put(x+1, y, "", 0, st)
		}
		x += w
	}
	return x
}

func (c *Canvas) put(x, y int, s string, w uint8, st Style) {
	if x < 0 || x >= c.W {
		return
	}
	cl := c.at(x, y)
	bg := cl.st.BG
	if w != 0 {
		c.clear(x, y)
	}
	if st.BG == none {
		st.BG = bg
	}
	*cl = cell{s: s, w: w, st: st}
}

// paint changes the style of cells without changing their text.
func (c *Canvas) paint(x, y, w int, f func(*Style)) {
	if y < 0 || y >= c.H {
		return
	}
	for xx := max(0, x); xx < min(c.W, x+w); xx++ {
		f(&c.at(xx, y).st)
	}
}

// render returns the canvas as text with SGR sequences.
func (c *Canvas) render() string {
	var b strings.Builder
	b.Grow(c.W * c.H * 4)
	for y := 0; y < c.H; y++ {
		var cur Style
		first := true
		for x := 0; x < c.W; x++ {
			cl := c.at(x, y)
			if cl.w == 0 {
				continue
			}
			if first || cl.st != cur {
				b.WriteString(sgr(cl.st))
				cur, first = cl.st, false
			}
			b.WriteString(cl.s)
		}
		b.WriteString("\x1b[0m")
		if y < c.H-1 {
			b.WriteByte('\n')
		}
	}
	return b.String()
}

func sgr(st Style) string {
	b := []byte("\x1b[0")
	if st.Bold {
		b = append(b, ";1"...)
	}
	if st.Faint {
		b = append(b, ";2"...)
	}
	if st.Italic {
		b = append(b, ";3"...)
	}
	if st.Reverse {
		b = append(b, ";7"...)
	}
	if st.Strike {
		b = append(b, ";9"...)
	}
	b = appendColor(b, st.FG, false)
	b = appendColor(b, st.BG, true)
	return string(append(b, 'm'))
}

func appendColor(b []byte, c Color, bg bool) []byte {
	switch c.k {
	case ckIndex:
		n := int(c.v)
		switch {
		case n < 8 && bg:
			return append(b, ";4"+strconv.Itoa(n)...)
		case n < 8:
			return append(b, ";3"+strconv.Itoa(n)...)
		case n < 16 && bg:
			return append(b, ";10"+strconv.Itoa(n-8)...)
		case n < 16:
			return append(b, ";9"+strconv.Itoa(n-8)...)
		case bg:
			return append(b, ";48;5;"+strconv.Itoa(n)...)
		default:
			return append(b, ";38;5;"+strconv.Itoa(n)...)
		}
	case ckRGB:
		p := ";38;2;"
		if bg {
			p = ";48;2;"
		}
		return append(b, p+strconv.Itoa(int(c.v>>16&255))+";"+strconv.Itoa(int(c.v>>8&255))+";"+strconv.Itoa(int(c.v&255))...)
	}
	return b
}

// width returns the display width of s.
func width(s string) int { return runewidth.StringWidth(s) }

// clip shortens s to w columns and marks the cut with an ellipsis.
func clip(s string, w int) string {
	if w <= 0 {
		return ""
	}
	if width(s) <= w {
		return s
	}
	return runewidth.Truncate(s, w, "…")
}

// padLeft right-aligns s in w columns.
func padLeft(s string, w int) string {
	if n := w - width(s); n > 0 {
		return strings.Repeat(" ", n) + s
	}
	return s
}

// wrap breaks s into lines of at most w columns, at spaces when it can.
func wrap(s string, w int) []string {
	if w <= 0 {
		return nil
	}
	var out []string
	for _, para := range strings.Split(s, "\n") {
		line := ""
		for _, word := range strings.Fields(para) {
			for width(word) > w {
				if line != "" {
					out = append(out, line)
					line = ""
				}
				cut := runewidth.Truncate(word, w, "")
				out = append(out, cut)
				word = word[len(cut):]
			}
			switch {
			case line == "":
				line = word
			case width(line)+1+width(word) <= w:
				line += " " + word
			default:
				out = append(out, line)
				line = word
			}
		}
		out = append(out, line)
	}
	return out
}
