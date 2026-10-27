package repo

// opKind is one step of a line diff.
type opKind uint8

const (
	opEq opKind = iota
	opDel
	opIns
)

type op struct {
	kind opKind
	a, b int // line index in the old and the new text
}

const maxEdits = 2000

// diffLines returns a shortest edit script from a to b with the Myers
// algorithm. It returns nil when the texts differ in more than maxEdits lines.
func diffLines(a, b []string) []op {
	// Equal lines at the ends do not need the search.
	pre := 0
	for pre < len(a) && pre < len(b) && a[pre] == b[pre] {
		pre++
	}
	suf := 0
	for suf < len(a)-pre && suf < len(b)-pre && a[len(a)-1-suf] == b[len(b)-1-suf] {
		suf++
	}
	ops := make([]op, 0, len(b)+8)
	for i := 0; i < pre; i++ {
		ops = append(ops, op{opEq, i, i})
	}
	mid, ok := myers(a[pre:len(a)-suf], b[pre:len(b)-suf])
	if !ok {
		return nil
	}
	for _, o := range mid {
		o.a += pre
		o.b += pre
		ops = append(ops, o)
	}
	for i := 0; i < suf; i++ {
		ops = append(ops, op{opEq, len(a) - suf + i, len(b) - suf + i})
	}
	return ops
}

func myers(a, b []string) ([]op, bool) {
	n, m := len(a), len(b)
	if n == 0 || m == 0 {
		ops := make([]op, 0, n+m)
		for i := 0; i < n; i++ {
			ops = append(ops, op{opDel, i, 0})
		}
		for j := 0; j < m; j++ {
			ops = append(ops, op{opIns, n, j})
		}
		return ops, true
	}
	maxD := min(n+m, maxEdits)
	off := maxD + 1
	v := make([]int, 2*maxD+3)
	var trace [][]int
	found := false
	for d := 0; d <= maxD && !found; d++ {
		// Keep only the part of the frontier that the walk back reads.
		trace = append(trace, append([]int(nil), v[off-d-1:off+d+2]...))
		for k := -d; k <= d; k += 2 {
			var x int
			if k == -d || (k != d && v[off+k-1] < v[off+k+1]) {
				x = v[off+k+1]
			} else {
				x = v[off+k-1] + 1
			}
			y := x - k
			for x < n && y < m && a[x] == b[y] {
				x++
				y++
			}
			v[off+k] = x
			if x >= n && y >= m {
				found = true
				break
			}
		}
	}
	if !found {
		return nil, false
	}
	// Walk back through the saved frontiers.
	var rev []op
	x, y := n, m
	for d := len(trace) - 1; d >= 0; d-- {
		vd := trace[d]
		at := func(k int) int { return vd[k+d+1] }
		k := x - y
		var pk int
		if k == -d || (k != d && at(k-1) < at(k+1)) {
			pk = k + 1
		} else {
			pk = k - 1
		}
		px := at(pk)
		py := px - pk
		for x > px && y > py {
			x--
			y--
			rev = append(rev, op{opEq, x, y})
		}
		if d > 0 {
			if x == px {
				y--
				rev = append(rev, op{opIns, x, y})
			} else {
				x--
				rev = append(rev, op{opDel, x, y})
			}
		}
	}
	for i, j := 0, len(rev)-1; i < j; i, j = i+1, j-1 {
		rev[i], rev[j] = rev[j], rev[i]
	}
	return rev, true
}
