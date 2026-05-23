// Banglish → Bangla phonetic transliteration.
//
// Lots of users instinctively type Bhoot FM search terms in English letters
// ("hospital", "bari", "ambulance") even though the transcripts are pure
// Bangla. Without help, those queries get zero results. This module turns
// Latin input into one or more Bangla candidate spellings, which the search
// layer then submits in place of (or in addition to) the raw query.
//
// Two stages:
//   1. Dictionary of common Bhoot-FM-relevant Banglish words → known Bangla.
//      Loan words like হাসপাতাল don't follow phonetic rules, so a hand list
//      covers the long tail of cases the algorithm gets wrong.
//   2. Algorithmic transliteration (Avro-style greedy longest-match) for
//      everything else.
//
// Tradeoffs accepted: there's no full inflection/sandhi engine here, and the
// algorithm produces phonetic approximations that may not match the exact
// graphemes used in transcripts. The dictionary lookup is what makes the
// experience feel sharp; the algorithm is the safety net.

(function () {
  "use strict";

  // ─── Curated dictionary ─────────────────────────────────────────────
  // Keep the keys lowercase; the lookup lowercases input before checking.
  // When in doubt, prefer the spelling that actually appears in Bhoot FM
  // transcripts (e.g., ভূত with long-uu vowel sign).
  const DICT = {
    // People & places that show up constantly on the show
    "russell": "রাসেল", "rasel": "রাসেল", "rj": "আরজে",
    "foorti": "ফুর্তি", "furti": "ফুর্তি",
    "radio": "রেডিও", "fm": "এফএম",
    "bangladesh": "বাংলাদেশ", "dhaka": "ঢাকা", "chittagong": "চট্টগ্রাম",
    "sylhet": "সিলেট", "khulna": "খুলনা", "rajshahi": "রাজশাহী",

    // Core horror vocabulary
    "bhoot": "ভূত", "bhut": "ভূত", "bhoy": "ভয়", "voy": "ভয়",
    "bhuter": "ভূতের", "bhutere": "ভূতের",
    "preto": "প্রেত", "pret": "প্রেত", "pretatma": "প্রেতাত্মা",
    "atma": "আত্মা", "atta": "আত্মা",
    "jin": "জিন", "djinn": "জিন",
    "pori": "পরী", "shaitan": "শয়তান", "shoytan": "শয়তান",
    "pisach": "পিশাচ", "pishach": "পিশাচ",
    "daini": "ডাইনি", "dayini": "ডাইনি",
    "chaya": "ছায়া", "chhaya": "ছায়া",
    "kankal": "কঙ্কাল",
    "mrityu": "মৃত্যু", "mritto": "মৃত্যু", "mrittu": "মৃত্যু",
    "kobor": "কবর", "kobar": "কবর", "kabar": "কবর",
    "lash": "লাশ", "shob": "শব",
    "golpo": "গল্প", "gappo": "গল্প",

    // Everyday nouns that come up in stories
    "bari": "বাড়ি", "baari": "বাড়ি", "barhi": "বাড়ি",
    "gari": "গাড়ি", "gaari": "গাড়ি",
    "ghor": "ঘর", "ghar": "ঘর",
    "raat": "রাত", "rat": "রাত", "rater": "রাতের",
    "din": "দিন", "shokal": "সকাল", "shondhya": "সন্ধ্যা",
    "sondhya": "সন্ধ্যা",
    "ma": "মা", "maa": "মা", "baba": "বাবা", "baap": "বাপ",
    "bhai": "ভাই", "bon": "বোন", "didi": "দিদি", "dada": "দাদা",
    "mama": "মামা", "khala": "খালা", "chacha": "চাচা",
    "bondhu": "বন্ধু", "bondu": "বন্ধু",
    "manush": "মানুষ", "manusher": "মানুষের",
    "meye": "মেয়ে", "meyer": "মেয়ের",
    "chele": "ছেলে", "cheler": "ছেলের",

    // Places
    "hospital": "হাসপাতাল", "hashpatal": "হাসপাতাল",
    "school": "স্কুল", "skul": "স্কুল",
    "doctor": "ডাক্তার", "daktar": "ডাক্তার",
    "ambulance": "অ্যাম্বুলেন্স", "ambulence": "অ্যাম্বুলেন্স",
    "police": "পুলিশ",
    "jongol": "জঙ্গল", "jangal": "জঙ্গল",
    "gram": "গ্রাম", "shohor": "শহর", "shahar": "শহর",
    "mosjid": "মসজিদ", "masjid": "মসজিদ",
    "mondir": "মন্দির", "mandir": "মন্দির",
    "rasta": "রাস্তা", "raasta": "রাস্তা",
    "nodi": "নদী", "pukur": "পুকুর",
    "bostir": "বস্তির", "village": "গ্রাম",

    // Verbs / common adjectives
    "khub": "খুব", "khoob": "খুব",
    "bhalo": "ভালো", "valo": "ভালো",
    "kharap": "খারাপ",
    "bhoyonkor": "ভয়ংকর", "voyongkor": "ভয়ংকর",
  };

  // ─── Phoneme tables (Avro-inspired, longest-match first) ────────────
  const VOWELS = {
    // 'a' alone is the inherent vowel (অ); kar form is empty so consonants
    // with no following vowel naturally read as <C>+inherent-a.
    "aa": { ind: "আ", kar: "া" },
    "a":  { ind: "অ", kar: ""  },
    "ii": { ind: "ঈ", kar: "ী" },
    "ee": { ind: "ঈ", kar: "ী" },
    "i":  { ind: "ই", kar: "ি" },
    "uu": { ind: "ঊ", kar: "ূ" },
    "oo": { ind: "ঊ", kar: "ূ" },
    "u":  { ind: "উ", kar: "ু" },
    "e":  { ind: "এ", kar: "ে" },
    "oi": { ind: "ঐ", kar: "ৈ" },
    "ai": { ind: "ঐ", kar: "ৈ" },
    "ou": { ind: "ঔ", kar: "ৌ" },
    "au": { ind: "ঔ", kar: "ৌ" },
    "o":  { ind: "ও", kar: "ো" },
  };

  const CONSONANTS = {
    "kkh": "ক্ষ", "chh": "ছ",
    "kh": "খ", "gh": "ঘ", "ng": "ং", "ch": "চ", "jh": "ঝ",
    "th": "থ", "dh": "ধ", "ph": "ফ", "bh": "ভ", "sh": "শ",
    "k": "ক", "g": "গ", "c": "চ", "j": "জ", "t": "ত", "d": "দ",
    "n": "ন", "p": "প", "b": "ব", "m": "ম", "y": "য়", "r": "র",
    "l": "ল", "v": "ভ", "w": "ও", "s": "স", "h": "হ", "f": "ফ",
    "z": "জ", "x": "ক্স", "q": "ক",
  };

  // Sorted keys for greedy longest-prefix matching.
  const VOWEL_KEYS = Object.keys(VOWELS).sort((a, b) => b.length - a.length);
  const CONSONANT_KEYS = Object.keys(CONSONANTS).sort((a, b) => b.length - a.length);

  function translitWord(word) {
    word = word.toLowerCase();
    let i = 0;
    let out = "";
    let lastWasConsonant = false;
    while (i < word.length) {
      let matched = null;
      let kind = null;
      for (const k of CONSONANT_KEYS) {
        if (word.startsWith(k, i)) { matched = k; kind = "C"; break; }
      }
      if (!matched) {
        for (const k of VOWEL_KEYS) {
          if (word.startsWith(k, i)) { matched = k; kind = "V"; break; }
        }
      }
      if (!matched) { i++; continue; }
      if (kind === "C") {
        // Halant joins two adjacent consonants into a conjunct.
        if (lastWasConsonant) out += "্";
        out += CONSONANTS[matched];
        lastWasConsonant = true;
      } else {
        const v = VOWELS[matched];
        out += lastWasConsonant ? v.kar : v.ind;
        lastWasConsonant = false;
      }
      i += matched.length;
    }
    return out;
  }

  // Apply dictionary first, fall back to algorithmic transliteration.
  function transliterateToken(tok) {
    const low = tok.toLowerCase();
    if (DICT[low]) return DICT[low];
    return translitWord(low);
  }

  // ─── Public entry point ─────────────────────────────────────────────
  // Returns { bangla, original, transformed } where:
  //   - transformed === true if input was non-Bangla and we converted it
  //   - bangla is the converted query (or the original if no conversion)
  function banglishToBangla(input) {
    const raw = (input || "").trim();
    if (!raw) return { bangla: "", original: raw, transformed: false };
    // If the input already contains Bangla characters, don't touch it —
    // the user knows what they want.
    if (/[ঀ-৿]/.test(raw)) {
      return { bangla: raw, original: raw, transformed: false };
    }
    // Only Latin / digits / whitespace from here on. Skip transliteration
    // entirely if there are no letters at all (e.g., a stray digit).
    if (!/[a-z]/i.test(raw)) {
      return { bangla: raw, original: raw, transformed: false };
    }
    const parts = raw.split(/(\s+)/);  // keep whitespace so words stay aligned
    const bangla = parts.map(p => /\s+/.test(p) ? p : transliterateToken(p)).join("");
    return {
      bangla,
      original: raw,
      transformed: bangla !== raw && /[ঀ-৿]/.test(bangla),
    };
  }

  window.banglishToBangla = banglishToBangla;
})();
