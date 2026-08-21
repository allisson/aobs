# The recorded-frame corpus

Raw V4L2 capture buffers, replayed from files by `../src/qr.rs`
(`05-testing-and-release.md` §6.3). They are bytes and nothing else, because that is what a
buffer is: the format, the width, the height and the stride arrive from `VIDIOC_S_FMT` and never
from the frame, so they live in the `CORPUS` table beside the test rather than in a header here.

That table also carries what each frame contains, why it is in the corpus, and how it was
produced — and the test asserts the contents, so the table cannot drift from the files without
failing.
