-- ============================================================
-- Jolly Phonics reference data: 7 groups, 42 letter sounds.
-- Run once, after schema.sql. Idempotent -- re-running updates the
-- example words and action hints without touching any test history,
-- because every row is matched on its stable `code`.
--
-- Ordering follows the standard Jolly Phonics teaching sequence. Two
-- notes on the printed forms:
--   * Group 2 opens with "c k" -- the two letters that both make the
--     /k/ sound, taught together. It is NOT the "ck" digraph (that is
--     taught later, with the alternative spellings).
--   * "oo" (group 5) and "th" (group 6) each appear twice with
--     different sounds, so they are keyed oo_short/oo_long and
--     th_unvoiced/th_voiced.
-- ============================================================

insert into phonics_groups (group_number, sounds_preview) values
  (1, 's a t i p n'),
  (2, 'c k  e h r m d'),
  (3, 'g o u l f b'),
  (4, 'ai j oa ie ee or'),
  (5, 'z w ng v oo oo'),
  (6, 'y x ch sh th th'),
  (7, 'qu ou oi ue er ar')
on conflict (group_number) do update set sounds_preview = excluded.sounds_preview;

insert into phonics_sounds (group_id, code, grapheme, label, example_word, action_hint, order_index)
select g.id, v.code, v.grapheme, v.label, v.example_word, v.action_hint, v.order_index
from (values
  -- Group 1
  (1, 's',           's',   's',            'snake',     'Weave hand like a snake, say ssss',            1),
  (1, 'a',           'a',   'a',            'ant',       'Wiggle fingers above elbow, say a a a',        2),
  (1, 't',           't',   't',            'tennis',    'Turn head side to side like watching tennis',  3),
  (1, 'i',           'i',   'i',            'insect',    'Wiggle fingers on nose, squeak i i i',         4),
  (1, 'p',           'p',   'p',            'puppy',     'Puff out short breaths, blowing out a candle', 5),
  (1, 'n',           'n',   'n',            'net',       'Arms out like a plane, say nnnn',              6),
  -- Group 2
  (2, 'c_k',         'c k', 'c k',          'cat / key', 'Raise hands and snap fingers like castanets',  1),
  (2, 'e',           'e',   'e',            'egg',       'Pretend to tap an egg on a pan, say e e e',    2),
  (2, 'h',           'h',   'h',            'hat',       'Hand on chest, breathe out fast: h h h',       3),
  (2, 'r',           'r',   'r',            'rat',       'Pretend to shake a rag, say rrrr',             4),
  (2, 'm',           'm',   'm',            'milk',      'Rub tummy, say mmmm -- yummy',                 5),
  (2, 'd',           'd',   'd',            'dog',       'Beat hands up and down like a drum',           6),
  -- Group 3
  (3, 'g',           'g',   'g',            'girl',      'Spiral hand down like water: g g g',           1),
  (3, 'o',           'o',   'o',            'orange',    'Flick a light switch on and off: o o',         2),
  (3, 'u',           'u',   'u',            'umbrella',  'Pretend to put up an umbrella: u u u',         3),
  (3, 'l',           'l',   'l',            'lolly',     'Pretend to lick a lolly, say llll',            4),
  (3, 'f',           'f',   'f',            'fish',      'Let hands go out and in like a balloon: ffff', 5),
  (3, 'b',           'b',   'b',            'ball',      'Pretend to hit a ball with a bat',             6),
  -- Group 4
  (4, 'ai',          'ai',  'ai',           'rain',      'Cup hand to ear, say ai? ai?',                 1),
  (4, 'j',           'j',   'j',            'jelly',     'Pretend to wobble like jelly, say j j j',      2),
  (4, 'oa',          'oa',  'oa',           'goat',      'Hands on cheeks: oh no! oa',                   3),
  (4, 'ie',          'ie',  'ie',           'tie',       'Point to your eye, shout ie!',                 4),
  (4, 'ee',          'ee',  'ee',           'sheep',     'Hands on head like donkey ears: ee',           5),
  (4, 'or',          'or',  'or',           'fork',      'Hands on head like donkey ears: or',           6),
  -- Group 5
  (5, 'z',           'z',   'z',            'zip',       'Arms out, zig-zag like a bee: zzzz',           1),
  (5, 'w',           'w',   'w',            'wind',      'Blow on your hand like the wind: wh wh',       2),
  (5, 'ng',          'ng',  'ng',           'ring',      'Pretend to lift a weight: nnng!',              3),
  (5, 'v',           'v',   'v',            'van',       'Pretend to drive a van, say vvvv',             4),
  (5, 'oo_short',    'oo',  'oo (book)',    'book',      'Move head like a cuckoo clock: short oo',      5),
  (5, 'oo_long',     'oo',  'oo (moon)',    'moon',      'Move head like a cuckoo clock: long oo',       6),
  -- Group 6
  (6, 'y',           'y',   'y',            'yellow',    'Pretend to eat yoghurt from a spoon: y y y',   1),
  (6, 'x',           'x',   'x',            'box',       'Pretend to take an x-ray photo: ks ks',        2),
  (6, 'ch',          'ch',  'ch',           'chip',      'Move arms like a train: ch ch ch',             3),
  (6, 'sh',          'sh',  'sh',           'ship',      'Finger to lips: shhhh',                        4),
  (6, 'th_unvoiced', 'th',  'th (thin)',    'thin',      'Tongue out, quiet th -- no buzz',              5),
  (6, 'th_voiced',   'th',  'th (this)',    'this',      'Tongue out, buzzy th -- voice on',             6),
  -- Group 7
  (7, 'qu',          'qu',  'qu',           'queen',     'Make a duck bill with your hand: qu qu',       1),
  (7, 'ou',          'ou',  'ou',           'cloud',     'Pretend to hurt a finger: ou! ou!',            2),
  (7, 'oi',          'oi',  'oi',           'coin',      'Cup hands and call out: oi! oi!',              3),
  (7, 'ue',          'ue',  'ue',           'blue',      'Point to people: you, you, you -- ue',         4),
  (7, 'er',          'er',  'er',           'mixer',     'Roll hands like a mixer whirring: ererer',     5),
  (7, 'ar',          'ar',  'ar',           'farm',      'Open mouth wide for the doctor: ar',           6)
) as v(group_number, code, grapheme, label, example_word, action_hint, order_index)
join phonics_groups g on g.group_number = v.group_number
on conflict (code) do update set
  group_id     = excluded.group_id,
  grapheme     = excluded.grapheme,
  label        = excluded.label,
  example_word = excluded.example_word,
  action_hint  = excluded.action_hint,
  order_index  = excluded.order_index;
