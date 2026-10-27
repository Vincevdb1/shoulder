package repo

import (
	"math/rand"
	"strings"
	"testing"
)

// apply rebuilds the new text from an edit script.
func apply(a, b []string, ops []op) ([]string, bool) {
	var out []string
	ai, bi := 0, 0
	for _, o := range ops {
		switch o.kind {
		case opEq:
			if o.a != ai || o.b != bi || a[ai] != b[bi] {
				return nil, false
			}
			out = append(out, a[ai])
			ai++
			bi++
		case opDel:
			if o.a != ai {
				return nil, false
			}
			ai++
		case opIns:
			if o.b != bi {
				return nil, false
			}
			out = append(out, b[bi])
			bi++
		}
	}
	return out, ai == len(a) && bi == len(b)
}

func TestDiffLinesRebuildsTarget(t *testing.T) {
	rng := rand.New(rand.NewSource(1))
	words := []string{"a", "b", "c", "d", "e"}
	for n := 0; n < 500; n++ {
		a := make([]string, rng.Intn(30))
		for i := range a {
			a[i] = words[rng.Intn(len(words))]
		}
		b := make([]string, rng.Intn(30))
		for i := range b {
			b[i] = words[rng.Intn(len(words))]
		}
		ops := diffLines(a, b)
		got, ok := apply(a, b, ops)
		if !ok || strings.Join(got, ",") != strings.Join(b, ",") {
			t.Fatalf("bad script for %v -> %v: %v", a, b, ops)
		}
	}
}

func TestDiffStates(t *testing.T) {
	f := &File{
		base:    []string{"one", "two", "three", "four", "five"},
		raw:     []string{"one", "TWO", "three", "five", "six"},
		hasBase: true,
	}
	f.diff()
	if f.Mod != 1 || f.Add != 1 || f.Del != 1 {
		t.Fatalf("counts: mod %d add %d del %d", f.Mod, f.Add, f.Del)
	}
	if f.Lines[1].State != Changed || f.Lines[1].Old != "two" {
		t.Fatalf("line 2: %+v", f.Lines[1])
	}
	if len(f.Lines[3].Above) != 1 || f.Lines[3].Above[0] != "four" {
		t.Fatalf("deleted line not above line 4: %+v", f.Lines[3])
	}
	if f.Lines[4].State != Added {
		t.Fatalf("line 5: %+v", f.Lines[4])
	}
	// The deletion above line 4 and the new line 5 touch, so they are one hunk.
	if len(f.Hunks) != 2 || f.Hunks[0] != 1 || f.Hunks[1] != 3 {
		t.Fatalf("hunks: %v", f.Hunks)
	}
}

func TestDiffDeleteAtEnd(t *testing.T) {
	f := &File{base: []string{"a", "b", "c"}, raw: []string{"a"}, hasBase: true}
	f.diff()
	if got := f.Lines[0].Below; len(got) != 2 {
		t.Fatalf("below: %v", got)
	}
}
