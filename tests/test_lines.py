import tempfile
import unittest
from pathlib import Path

from helpers import pw, seg, upload, w, wav

from craig_transcriber.project import Project
from craig_transcriber.transcribe import (
    lines_from_segments,
)


def judged(*lines):
    """Save Lines (dicts with start, end, text) for one Speaker and read them back through
    Project.state()."""
    with tempfile.TemporaryDirectory() as d:
        p = Project(Path(d) / "work")
        upload(p, "1-a.wav", wav())
        p.replace_lines(p.state()["speakers"][0]["id"], [{"conf": -0.1, **ln} for ln in lines])
        return p.state()["lines"]


def made_up(text):
    return {"repeated phrase", "foreign letters"} & set(
        judged({"start": 0.0, "end": 3.0, "text": text})[0]["reasons"]
    )


class HallucinationRuleTest(unittest.TestCase):
    def test_flags_repeats_and_foreign_scripts(self):
        for text in [
            "แก ร ั ติ เลย อี เข ีย บ อี เข ีย บ อี เข ีย บ อี เข ีย บ ไม่ ทัน พอ เล่น",
            "อีเขียบ อีเขียบ อีเขียบ อีเขียบ",
            "กี่หน้ากี่หน้ากี่หน้ากี่หน้า",
            "además habíaон",
            "складดิงตรงนี้",
            "เออ ตอนนี้一點ก็เดี๋ยว",
            "Mike is cursing too, Γειά",
        ]:
            self.assertTrue(made_up(text), text)

    def test_keeps_normal_thai_english_and_mixed(self):
        for text in [
            "เรียนแพทย์ดีกว่า",
            "No Way",
            "KMIT Open Courtware",
            "Essential Principal เลยนะเว้ย",
            "อ่า ฮ่า ฮ่า ฮ่า",
            "เล่นๆ ตอนข้าง ตรงชีพหว่ะ",
            "เสียไป ๆ บางเมื่อ ๆ ๆ เยอะ ๆ",
            "เล่มละพัน 1,000 บาท?",
            "Sami in år 2000",
            "Tiếng Việt",
            "นะนะนะนะนะ",
            "ไม่ไม่ไม่ไม่",
            "ฮ่าฮ่าฮ่าฮ่า",
            "ha ha ha ha",
            "555555555",
            "1000000000",
            "กี่หน้ากี่หน้ากี่หน้า",
            "อีเขียบ อีเขียบ อีเขียบ",
        ]:
            self.assertFalse(made_up(text), text)


def lines(*segments):
    return [
        (ln["text"], round(ln["start"], 2), round(ln["end"], 2))
        for ln in lines_from_segments(segments)
    ]


def full_lines(*segments):
    return list(lines_from_segments(segments))


class LinesFromSegmentsTest(unittest.TestCase):
    def test_whole_segment_line_carries_all_its_words(self):
        words = [w(" hello", 0.0, 0.4, 0.2), w(" world", 0.4, 0.8)]
        self.assertEqual(
            full_lines({**seg(0, " hello world"), "words": words})[0]["words"],
            [pw(" hello", 0.2), pw(" world")],
        )

    def test_segment_without_words_gives_empty_words(self):
        self.assertEqual(full_lines(seg(0, "hello"))[0]["words"], [])

    def test_split_line_carries_only_its_own_words(self):
        words = [
            w(" one", 0.0, 0.3),
            w(" two", 0.3, 0.6, 0.1),
            w(" three", 5.0, 5.3),
            w(" four", 5.3, 5.6),
        ]
        got = full_lines({**seg(0, "one two three four"), "end": 5.6, "words": words})
        self.assertEqual(
            [(ln["text"], ln["words"]) for ln in got],
            [
                ("one two", [pw(" one"), pw(" two", 0.1)]),
                ("three four", [pw(" three"), pw(" four")]),
            ],
        )

    def test_joined_fragments_carry_all_parts_words_in_order(self):
        def piece(t, a):
            return {**seg(a, t), "end": a + 0.1, "words": [w(t, a, a + 0.1, 0.4)]}

        got = full_lines(piece("ก", 0.0), piece("็คือ", 0.1))
        self.assertEqual(
            [(ln["text"], ln["words"]) for ln in got], [("ก็คือ", [pw("ก", 0.4), pw("็คือ", 0.4)])]
        )

    def test_segment_without_words_is_one_line_and_filters_still_apply(self):
        self.assertEqual(
            lines(
                seg(0, " hello "),
                seg(1, "  "),
                seg(2, "noise", conf=-1.5, no_speech=0.9),
                seg(3, "world"),
            ),
            [("hello", 0, 1), ("world", 3, 4)],
        )

    def test_thai_pause_moves_the_stray_piece_to_the_next_line(self):
        words = [
            w(" ผม", 0.0, 0.3),
            w("เรียน", 0.3, 0.8),
            w(" อย", 0.8, 0.9),
            w("าก", 5.4, 5.6),
            w("เรียน", 5.6, 6.0),
        ]
        self.assertEqual(
            lines({**seg(0, "ผมเรียน อยากเรียน"), "end": 6.0, "words": words}),
            [("ผมเรียน", 0.0, 0.8), ("อยากเรียน", 5.4, 6.0)],
        )

    def test_no_word_start_nearby_cuts_at_the_pause(self):
        words = [w("ก", 0.0, 0.2), w("าร", 0.2, 0.4), w("บ", 2.5, 2.7), w("ัญชี", 2.7, 3.0)]
        self.assertEqual(
            lines({**seg(0, "การบัญชี"), "end": 3.0, "words": words}),
            [("การ", 0.0, 0.4), ("บัญชี", 2.5, 3.0)],
        )

    def test_fallback_cut_never_splits_a_thai_syllable(self):
        dependent = [w("เล่น", 0.0, 0.4), w("ก", 0.4, 0.5), w("าร", 3.0, 3.2), w("บ้าน", 3.2, 3.5)]
        self.assertEqual(
            lines({**seg(0, "เล่นการบ้าน"), "end": 3.5, "words": dependent}),
            [("เล่น", 0.0, 0.4), ("การบ้าน", 3.0, 3.5)],
        )
        leading = [w("ดี", 0.0, 0.3), w("โ", 0.3, 0.4), w("อ", 2.0, 2.1), w("เค", 2.1, 2.3)]
        self.assertEqual(
            lines({**seg(0, "ดีโอเค"), "end": 2.3, "words": leading}),
            [("ดี", 0.0, 0.3), ("โอเค", 2.0, 2.3)],
        )

    def test_syllable_piece_between_two_pauses_joins_the_next_line(self):
        words = [
            w("ดี", 0.0, 0.3),
            w("ก", 1.0, 1.1),
            w("าร", 2.0, 2.2),
            w(" ม", 2.2, 2.3),
            w("า", 4.0, 4.2),
        ]
        self.assertEqual(
            lines({**seg(0, "ดีการ มา"), "end": 4.2, "words": words}),
            [("ดี", 0.0, 0.3), ("การ", 2.0, 2.2), ("มา", 4.0, 4.2)],
        )

    def test_english_after_thai_counts_as_a_word_start(self):
        words = [w("โหลด", 0.0, 0.4), w("ห", 0.4, 0.5), w("KM", 0.5, 0.6), w("IT", 1.4, 1.6)]
        self.assertEqual(
            lines({**seg(0, "โหลดหKMIT"), "end": 1.6, "words": words}),
            [("โหลดห", 0.0, 0.5), ("KMIT", 1.4, 1.6)],
        )

    def test_run_of_one_piece_segments_joins_into_one_line_with_the_next(self):
        def piece(t, a):
            return {**seg(a, t), "end": a + 0.1}

        self.assertEqual(
            lines(
                piece(" ม", 0.0),
                piece("ั", 0.1),
                piece("น", 0.2),
                piece("ก", 0.3),
                piece("็", 0.4),
                {**seg(0.5, "จะไปเลย"), "end": 2.0},
            ),
            [("มันก็จะไปเลย", 0.0, 2.0)],
        )

    def test_line_cut_inside_a_word_joins_the_next_even_after_a_pause(self):
        self.assertEqual(
            lines(seg(0, "ก"), seg(3, "็คือแบบว่า"), seg(8, "โ"), seg(12, "อเค")),
            [("ก็คือแบบว่า", 0, 4), ("โอเค", 8, 13)],
        )

    def test_tiny_lines_far_apart_stay_separate(self):
        self.assertEqual(lines(seg(0, "ใช่"), seg(5, "ครับ")), [("ใช่", 0, 1), ("ครับ", 5, 6)])

    def test_joined_run_stays_within_twelve_seconds(self):
        out = lines(*[{**seg(i * 0.5, "ก"), "end": i * 0.5 + 0.5} for i in range(30)])
        self.assertGreater(len(out), 1)
        self.assertTrue(all(end - start <= 12 for _, start, end in out))
        self.assertEqual("".join(t for t, _, _ in out), "ก" * 30)

    def test_joined_english_pieces_keep_a_space(self):
        def piece(t, a):
            return {**seg(a, t), "end": a + 0.1}

        self.assertEqual(
            lines(piece("go", 0.0), piece("to", 0.1), {**seg(0.2, "bed"), "end": 1.0}),
            [("go to bed", 0.0, 1.0)],
        )

    def test_short_pauses_do_not_split(self):
        words = [w(" ก็", 0.0, 0.3), w(" จริง", 0.8, 1.2)]
        self.assertEqual(
            lines({**seg(0, "ก็ จริง"), "end": 1.2, "words": words}), [("ก็ จริง", 0.0, 1.2)]
        )

    def test_line_over_twelve_seconds_splits_at_its_biggest_pause(self):
        words = [w(f" w{i}", i * 0.55, i * 0.55 + 0.5) for i in range(15)]
        words += [
            w(f" w{i}", 8.6 + (i - 15) * 0.55, 8.6 + (i - 15) * 0.55 + 0.5) for i in range(15, 30)
        ]
        out = lines({**seg(0, "x"), "end": 16.8, "words": words})
        self.assertEqual(
            [(t.split()[0], t.split()[-1], a, b) for t, a, b in out],
            [("w0", "w14", 0.0, 8.2), ("w15", "w29", 8.6, 16.8)],
        )

    def test_impossibly_fast_line_is_flagged_not_dropped(self):
        out = judged(
            *lines_from_segments(
                [
                    {**seg(57.2, "สินค้า คงเหลือ สิบเอ็ด บาท"), "end": 57.8},
                    {**seg(60.0, "เออ แพงจังอะ"), "end": 61.0},
                ]
            )
        )
        self.assertEqual(
            [(ln["text"], ln["reasons"]) for ln in out],
            [("สินค้า คงเหลือ สิบเอ็ด บาท", ["timing"]), ("เออ แพงจังอะ", [])],
        )

    def test_repeat_needs_four_in_a_row_and_short_lines_are_never_too_fast(self):
        out = judged(
            *lines_from_segments(
                [
                    {**seg(0, "กี่หน้ากี่หน้ากี่หน้า"), "end": 3.0},
                    {**seg(3, "กี่หน้ากี่หน้ากี่หน้ากี่หน้า"), "end": 6.0},
                    {**seg(6, "ขอบคุณครับ"), "end": 6.1},
                    {**seg(7, "ขอบคุณครับขอบคุณครับ"), "end": 7.5},
                    {**seg(9, "สวัสดีครับ ผมชื่อสมชาย"), "end": 9.5},
                    {**seg(10, "Gamma Γειά"), "end": 12.0},
                ]
            )
        )
        self.assertEqual([ln["unsure"] for ln in out], [False, True, False, True, True, True])

    def test_split_lines_get_their_own_confidence(self):
        words = [w(" ดี", 0.0, 0.4, 0.9), w(" มาก", 0.4, 0.8, 0.9), w(" xq", 3.0, 3.4, 0.05)]
        out = list(
            lines_from_segments([{**seg(0, "ดี มาก xq", conf=-0.5), "end": 3.4, "words": words}])
        )
        self.assertEqual([ln["text"] for ln in out], ["ดี มาก", "xq"])
        self.assertAlmostEqual(out[0]["conf"], -0.105, places=3)
        self.assertAlmostEqual(out[1]["conf"], -2.996, places=3)

    def test_unsplit_line_keeps_the_segment_confidence(self):
        words = [w(" ดี", 0.0, 0.4, 0.1), w(" มาก", 0.5, 0.8, 0.1)]
        out = list(
            lines_from_segments([{**seg(0, "ดี มาก", conf=-0.5), "end": 0.8, "words": words}])
        )
        self.assertEqual(out[0]["conf"], -0.5)


if __name__ == "__main__":
    unittest.main()
