package ui

import (
	"path/filepath"
	"strings"
	"unicode"

	"github.com/alecthomas/chroma/v2"
	"github.com/alecthomas/chroma/v2/lexers"
)

const tabWidth = 4

type span struct {
	text string
	role role
}

// highlighted is the syntax colored text of one file version.
type highlighted struct {
	version int
	lang    string
	lines   [][]span
}

const maxHighlight = 1 << 20

func lexerFor(path string, text string) chroma.Lexer {
	l := lexers.Match(filepath.Base(path))
	if l == nil {
		head := text
		if len(head) > 4096 {
			head = head[:4096]
		}
		l = lexers.Analyse(head)
	}
	return l
}

// highlight splits each line into colored spans. It expands tabs.
func highlight(path string, lines []string) ([][]span, string) {
	text := strings.Join(lines, "\n")
	out := make([][]span, len(lines))
	lexer := lexerFor(path, text)
	lang := ""
	if lexer != nil {
		lang = strings.ToLower(lexer.Config().Name)
	}
	if lexer == nil || len(text) > maxHighlight {
		for i, l := range lines {
			out[i] = []span{{text: expandTabs(l, 0), role: rFG}}
		}
		return out, lang
	}
	it, err := chroma.Coalesce(lexer).Tokenise(nil, text)
	if err != nil {
		for i, l := range lines {
			out[i] = []span{{text: expandTabs(l, 0), role: rFG}}
		}
		return out, lang
	}
	row, col := 0, 0
	for tok := it(); tok != chroma.EOF; tok = it() {
		r := roleOf(tok.Type)
		parts := strings.Split(tok.Value, "\n")
		for i, p := range parts {
			if i > 0 {
				row++
				col = 0
			}
			if p == "" || row >= len(out) {
				continue
			}
			p = expandTabs(p, col)
			col += width(p)
			out[row] = append(out[row], span{text: p, role: r})
		}
	}
	for i := range out {
		callsAsFunctions(out[i])
	}
	return out, lang
}

func roleOf(t chroma.TokenType) role {
	switch {
	case t == chroma.CommentPreproc || t == chroma.CommentPreprocFile:
		return rMac
	case t.InCategory(chroma.Comment):
		return rCom
	case t == chroma.KeywordType:
		return rTy
	case t == chroma.KeywordConstant:
		return rNum
	case t.InCategory(chroma.Keyword):
		return rKw
	case t.InSubCategory(chroma.LiteralString):
		return rStr
	case t.InSubCategory(chroma.LiteralNumber):
		return rNum
	case t == chroma.NameFunction || t == chroma.NameFunctionMagic || t == chroma.NameBuiltin:
		return rFn
	case t == chroma.NameClass || t == chroma.NameException || t == chroma.NameBuiltinPseudo:
		return rTy
	case t == chroma.NameNamespace:
		return rNs
	case t == chroma.NameDecorator || t == chroma.NameAttribute:
		return rMac
	case t == chroma.NameTag:
		return rKw
	case t == chroma.NameConstant:
		return rNum
	case t.InCategory(chroma.Operator) || t.InCategory(chroma.Punctuation):
		return rPun
	case t == chroma.GenericHeading || t == chroma.GenericSubheading:
		return rKw
	case t == chroma.GenericInserted:
		return rStr
	case t == chroma.GenericDeleted:
		return rKw
	}
	return rFG
}

// callsAsFunctions colors a plain name that an opening parenthesis follows,
// as the design does for calls.
func callsAsFunctions(sp []span) {
	for i := 0; i+1 < len(sp); i++ {
		if sp[i].role != rFG || !isIdent(sp[i].text) {
			continue
		}
		if strings.HasPrefix(sp[i+1].text, "(") {
			sp[i].role = rFn
		}
	}
}

func isIdent(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if !unicode.IsLetter(r) && !unicode.IsDigit(r) && r != '_' {
			return false
		}
	}
	return true
}

// expandTabs replaces tabs with spaces to the next tab stop. col is the
// column where s starts.
func expandTabs(s string, col int) string {
	if !strings.Contains(s, "\t") {
		return s
	}
	var b strings.Builder
	for _, r := range s {
		if r == '\t' {
			n := tabWidth - col%tabWidth
			b.WriteString(strings.Repeat(" ", n))
			col += n
			continue
		}
		b.WriteRune(r)
		col += width(string(r))
	}
	return b.String()
}

// displayCol converts a rune offset in a raw line to a screen column.
func displayCol(line string, n int) int {
	col := 0
	for i, r := range []rune(line) {
		if i >= n {
			break
		}
		if r == '\t' {
			col += tabWidth - col%tabWidth
		} else {
			col += width(string(r))
		}
	}
	return col
}
