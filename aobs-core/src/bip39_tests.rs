//! BIP-39 in both directions, against the published vectors and two properties
//! (`05-testing-and-release.md` §2, §3).
//!
//! The tables are at the bottom of the file. The Japanese ones are **mandatory, not
//! optional**: they are the only vectors in the whole suite that tell NFKD from NFD, and an
//! implementation reaching for the wrong form passes everything else here.

use bitcoin::hashes::{sha256, Hash as _, HashEngine as _};
use bitcoin::hex::FromHex;
use proptest::prelude::*;
use unicode_normalization::UnicodeNormalization;

use super::*;

/// The digest BIP-39 itself publishes for `english.txt`, over the 2048 words each followed by
/// a newline. A word mangled by an edit to `english.rs` fails here rather than deriving
/// somebody else's wallet.
const WORDLIST_SHA256: &str = "2f5eed53a4727b4bf8880d8f3f199efc90e58503646d9ff8eff3a2ed3b24dbda";

fn unhex(hex: &str) -> Vec<u8> {
    Vec::<u8>::from_hex(hex).expect("a test vector is valid hex")
}

/// The wordlist position of `word`. Tests only: production never needs it, because the import
/// reducer matches by prefix and hands over indices (its own slice), and generation goes the
/// other way.
fn index_of(word: &str) -> u16 {
    let position = WORDS.iter().position(|candidate| *candidate == word);
    u16::try_from(position.expect("a vector's word is in the list")).expect("2048 fits in a u16")
}

fn indices_of(sentence: &str) -> Vec<u16> {
    sentence.split_whitespace().map(index_of).collect()
}

fn trezor() -> Passphrase {
    Passphrase::new("TREZOR").expect("6 bytes fit")
}

/// Both directions plus the seed, at every accepted length, over both tables.
///
/// The two tables together are 12, 15, 18, 21 and 24 words: the canonical suite covers three
/// of the five and [`ENGLISH_15_21`] carries the other two.
#[test]
fn english_vectors_in_both_directions_at_all_five_lengths() {
    let mut lengths = std::collections::BTreeSet::new();

    for (entropy_hex, sentence, seed_hex) in ENGLISH.iter().chain(ENGLISH_15_21) {
        let entropy = Entropy::new(&unhex(entropy_hex)).expect("a vector is at most 32 bytes");

        // entropy -> mnemonic
        let mnemonic = Mnemonic::from_entropy(&entropy).expect("a vector is an accepted length");
        let rendered: Vec<&str> = (0..mnemonic.word_count())
            .map(|at| mnemonic.word(at).expect("in range"))
            .collect();
        assert_eq!(rendered.join(" "), *sentence, "{entropy_hex}");

        // mnemonic -> entropy, from the indices the reducer would have collected
        let reimported =
            Mnemonic::from_indices(&indices_of(sentence)).expect("a vector's checksum holds");
        assert_eq!(
            reimported.entropy().as_bytes(),
            entropy.as_bytes(),
            "{entropy_hex}"
        );

        // mnemonic -> seed, passphrase "TREZOR"
        assert_eq!(
            mnemonic.seed(&trezor()).as_bytes(),
            unhex(seed_hex),
            "{entropy_hex}"
        );

        lengths.insert(mnemonic.word_count());
    }

    assert_eq!(lengths.into_iter().collect::<Vec<_>>(), LENGTHS);
}

/// The NFKD discriminator. Every seed here is derived through [`Passphrase`], which normalises
/// at construction, so a passphrase held in any other form fails all 24.
///
/// The mnemonics are Japanese and therefore not in our wordlist — English only in v1 — so they
/// enter at the PBKDF2 seam directly, normalised by the test. That is the one thing this file
/// asserts about a phrase [`Mnemonic`] cannot hold, and it is asserted because the seed step
/// is wordlist-independent and the compatibility character is in the *passphrase*.
#[test]
fn the_japanese_vectors_pin_nfkd_rather_than_nfd() {
    let passphrase = Passphrase::new(JP_PASSPHRASE).expect("78 bytes NFKD fit");

    for (entropy_hex, sentence, seed_hex) in JAPANESE {
        let nfkd: String = sentence.nfkd().collect();
        let seed = pbkdf2_hmac_sha512(nfkd.as_bytes(), passphrase.as_bytes());
        assert_eq!(seed.as_bytes(), unhex(seed_hex), "{entropy_hex}");
    }
}

/// And the other half of that claim: the vectors above genuinely *discriminate*. Under NFD —
/// the form that leaves U+334D alone — every one of them is wrong, which is what makes them
/// worth carrying rather than 24 more rows that any normalisation would pass.
#[test]
fn nfd_fails_the_japanese_vectors() {
    let nfd_passphrase: String = JP_PASSPHRASE.nfd().collect();
    assert_ne!(nfd_passphrase, JP_PASSPHRASE.nfkd().collect::<String>());

    for (entropy_hex, sentence, seed_hex) in JAPANESE {
        let nfd: String = sentence.nfd().collect();
        let seed = pbkdf2_hmac_sha512(nfd.as_bytes(), nfd_passphrase.as_bytes());
        assert_ne!(seed.as_bytes(), unhex(seed_hex), "{entropy_hex}");
    }
}

/// Generation is 24 words, always. There is no length parameter to pass and no truncation
/// branch to take: the 32 bytes [`crate::entropy::mix`] produces are used whole.
#[test]
fn generation_is_always_24_words() {
    let entropy = crate::entropy::mix(crate::secret::Csprng32::new([0x5a; 32]), None, None);
    let mnemonic = Mnemonic::from_entropy(&entropy).expect("32 bytes is an accepted length");
    assert_eq!(mnemonic.word_count(), 24);
    assert_eq!(mnemonic.entropy().as_bytes(), entropy.as_bytes());
}

#[test]
fn entropy_outside_the_five_lengths_is_refused() {
    for length in [0usize, 1, 15, 17, 21, 31] {
        let entropy = Entropy::new(&vec![0u8; length]).expect("under the cap");
        assert_eq!(
            Mnemonic::from_entropy(&entropy).err(),
            Some(Error::EntropyLength(length))
        );
    }
    for length in [16usize, 20, 24, 28, 32] {
        let entropy = Entropy::new(&vec![0u8; length]).expect("under the cap");
        assert!(Mnemonic::from_entropy(&entropy).is_ok(), "{length}");
    }
}

#[test]
fn a_word_count_outside_the_five_lengths_is_refused() {
    for count in [0usize, 11, 13, 23] {
        let refused = Mnemonic::from_indices(&vec![0u16; count]).err();
        assert_eq!(refused, Some(Error::WordCount(count)));
    }
}

#[test]
fn a_word_index_off_the_list_is_refused() {
    let mut indices = indices_of(ENGLISH[0].1);
    indices[3] = 2048;
    assert_eq!(
        Mnemonic::from_indices(&indices).err(),
        Some(Error::WordIndex(2048))
    );
}

/// Real words in the wrong place — the only failure the checksum can ever report, because an
/// off-list word is unrepresentable. The refusal names no word, and there is no API here that
/// could.
#[test]
fn two_swapped_words_fail_the_checksum() {
    let (_, sentence, _) = ENGLISH[9];
    let mut indices = indices_of(sentence);
    assert_eq!(indices.len(), 24);
    indices.swap(0, 1);
    assert_eq!(
        Mnemonic::from_indices(&indices).err(),
        Some(Error::Checksum)
    );

    // And a single wrong word, at the front of a phrase, where a device that pointed at a
    // position would be guessing.
    let mut indices = indices_of(ENGLISH[0].1);
    indices[0] = index_of("ability");
    assert_eq!(
        Mnemonic::from_indices(&indices).err(),
        Some(Error::Checksum)
    );
}

#[test]
fn word_reads_past_the_phrase_as_none() {
    let mnemonic = Mnemonic::from_indices(&indices_of(ENGLISH[0].1)).expect("valid");
    assert_eq!(mnemonic.word_count(), 12);
    assert_eq!(mnemonic.word(0), Some("abandon"));
    assert_eq!(mnemonic.word(11), Some("about"));
    assert_eq!(mnemonic.word(12), None);
    assert_eq!(mnemonic.word(24), None);
}

/// **Never trim.** `"a"`, `" a"` and `"a "` are three different wallets, and no passphrase is
/// the fourth.
#[test]
fn the_passphrase_is_never_trimmed_and_empty_is_its_own_seed() {
    let mnemonic = Mnemonic::from_indices(&indices_of(ENGLISH[0].1)).expect("valid");
    let seeds: Vec<Vec<u8>> = ["", "a", " a", "a ", "TREZOR"]
        .iter()
        .map(|text| {
            mnemonic
                .seed(&Passphrase::new(text).expect("fits"))
                .as_bytes()
                .to_vec()
        })
        .collect();

    for (at, seed) in seeds.iter().enumerate() {
        for other in &seeds[at + 1..] {
            assert_ne!(seed, other);
        }
    }
    // The empty passphrase is the no-passphrase case and nothing else: the canonical
    // 12-word vector's own seed is under "TREZOR", so this pins that they differ at all.
    assert_eq!(seeds[4], unhex(ENGLISH[0].2));
}

#[test]
fn the_wordlist_is_the_one_bip39_publishes() {
    assert_eq!(WORDS.len(), 2048);

    let mut engine = sha256::Hash::engine();
    for word in WORDS {
        engine.input(word.as_bytes());
        engine.input(b"\n");
    }
    assert_eq!(
        sha256::Hash::from_engine(engine).to_string(),
        WORDLIST_SHA256
    );
}

/// The three list properties the code above leans on: sorted (so a position lookup is
/// meaningful), ASCII and at most 8 bytes (so `MAX_SENTENCE` holds), and its own NFKD form (so
/// [`Mnemonic::seed`] may skip normalising the phrase).
#[test]
fn every_word_is_ascii_short_and_already_nfkd() {
    let mut previous = "";
    for word in WORDS {
        assert!(
            word.is_ascii() && word.chars().all(|c| c.is_ascii_lowercase()),
            "{word}"
        );
        assert!(word.len() <= 8, "{word}");
        assert!(previous < word, "{previous} then {word}");
        assert_eq!(word.nfkd().collect::<String>(), *word, "{word}");
        previous = word;
    }
    assert_eq!(MAX_SENTENCE, 24 * 8 + 23);
}

/// The claim `02-core.md` §4 rests prefix matching on: every word is unique within its first
/// four characters. The reducer is another slice's, but the property it needs is this file's.
#[test]
fn every_word_is_unique_within_four_characters() {
    let mut prefixes: Vec<&str> = WORDS
        .iter()
        .map(|word| &word[..word.len().min(4)])
        .collect();
    prefixes.sort_unstable();
    let count = prefixes.len();
    prefixes.dedup();
    assert_eq!(prefixes.len(), count);
}

proptest! {
    /// The round trip, at every accepted length: `entropy → mnemonic → entropy` is the
    /// identity. This is the property the import path's correctness reduces to.
    #[test]
    fn entropy_survives_the_round_trip_at_every_length(
        bytes: [u8; 32],
        which: prop::sample::Index,
    ) {
        let length = *which.get(&LENGTHS) * 11 / 33 * 4;
        let entropy = Entropy::new(&bytes[..length]).expect("at most 32");

        let mnemonic = Mnemonic::from_entropy(&entropy).expect("an accepted length");
        prop_assert_eq!(mnemonic.word_count() * 11 / 33 * 4, length);
        let recovered = mnemonic.entropy();
        prop_assert_eq!(recovered.as_bytes(), entropy.as_bytes());

        // And through the indices, which is the path an import actually takes.
        let indices: Vec<u16> =
            (0..mnemonic.word_count()).map(|at| index_of(mnemonic.word(at).unwrap())).collect();
        let reimported = Mnemonic::from_indices(&indices).expect("our own checksum holds");
        let reimported = reimported.entropy();
        prop_assert_eq!(reimported.as_bytes(), entropy.as_bytes());
    }

    /// A phrase our own generator produced always passes our own checksum — the invariant that
    /// makes [`Mnemonic`]'s validity-by-construction true rather than hoped for.
    #[test]
    fn a_generated_phrase_always_re_imports(bytes: [u8; 32]) {
        let entropy = crate::entropy::mix(
            crate::secret::Csprng32::new(bytes),
            Some(crate::secret::Luma::new(&bytes)),
            Some(crate::secret::Dice::new(b"6533214")),
        );
        let mnemonic = Mnemonic::from_entropy(&entropy).expect("32 bytes");
        let indices: Vec<u16> =
            (0..24).map(|at| index_of(mnemonic.word(at).unwrap())).collect();
        prop_assert!(Mnemonic::from_indices(&indices).is_ok());
    }
}

// --- The tables -------------------------------------------------------------------

/// The canonical BIP-39 English vectors: `(entropy_hex, mnemonic, seed_hex)`, passphrase
/// `"TREZOR"`. Verbatim from the set BIP-39 itself points at,
/// <https://github.com/trezor/python-mnemonic/blob/master/vectors.json>. The `xprv` fourth
/// column is dropped: BIP-32 derivation is #71's slice, not this one.
const ENGLISH: &[(&str, &str, &str)] = &[
    (
        "00000000000000000000000000000000",
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
        "c55257c360c07c72029aebc1b53c05ed0362ada38ead3e3e9efa3708e53495531f09a6987599d18264c1e1c92f2cf141630c7a3c4ab7c81b2f001698e7463b04",
    ),
    (
        "7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f",
        "legal winner thank year wave sausage worth useful legal winner thank yellow",
        "2e8905819b8723fe2c1d161860e5ee1830318dbf49a83bd451cfb8440c28bd6fa457fe1296106559a3c80937a1c1069be3a3a5bd381ee6260e8d9739fce1f607",
    ),
    (
        "80808080808080808080808080808080",
        "letter advice cage absurd amount doctor acoustic avoid letter advice cage above",
        "d71de856f81a8acc65e6fc851a38d4d7ec216fd0796d0a6827a3ad6ed5511a30fa280f12eb2e47ed2ac03b5c462a0358d18d69fe4f985ec81778c1b370b652a8",
    ),
    (
        "ffffffffffffffffffffffffffffffff",
        "zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo wrong",
        "ac27495480225222079d7be181583751e86f571027b0497b5b5d11218e0a8a13332572917f0f8e5a589620c6f15b11c61dee327651a14c34e18231052e48c069",
    ),
    (
        "000000000000000000000000000000000000000000000000",
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon agent",
        "035895f2f481b1b0f01fcf8c289c794660b289981a78f8106447707fdd9666ca06da5a9a565181599b79f53b844d8a71dd9f439c52a3d7b3e8a79c906ac845fa",
    ),
    (
        "7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f",
        "legal winner thank year wave sausage worth useful legal winner thank year wave sausage worth useful legal will",
        "f2b94508732bcbacbcc020faefecfc89feafa6649a5491b8c952cede496c214a0c7b3c392d168748f2d4a612bada0753b52a1c7ac53c1e93abd5c6320b9e95dd",
    ),
    (
        "808080808080808080808080808080808080808080808080",
        "letter advice cage absurd amount doctor acoustic avoid letter advice cage absurd amount doctor acoustic avoid letter always",
        "107d7c02a5aa6f38c58083ff74f04c607c2d2c0ecc55501dadd72d025b751bc27fe913ffb796f841c49b1d33b610cf0e91d3aa239027f5e99fe4ce9e5088cd65",
    ),
    (
        "ffffffffffffffffffffffffffffffffffffffffffffffff",
        "zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo when",
        "0cd6e5d827bb62eb8fc1e262254223817fd068a74b5b449cc2f667c3f1f985a76379b43348d952e2265b4cd129090758b3e3c2c49103b5051aac2eaeb890a528",
    ),
    (
        "0000000000000000000000000000000000000000000000000000000000000000",
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon art",
        "bda85446c68413707090a52022edd26a1c9462295029f2e60cd7c4f2bbd3097170af7a4d73245cafa9c3cca8d561a7c3de6f5d4a10be8ed2a5e608d68f92fcc8",
    ),
    (
        "7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f",
        "legal winner thank year wave sausage worth useful legal winner thank year wave sausage worth useful legal winner thank year wave sausage worth title",
        "bc09fca1804f7e69da93c2f2028eb238c227f2e9dda30cd63699232578480a4021b146ad717fbb7e451ce9eb835f43620bf5c514db0f8add49f5d121449d3e87",
    ),
    (
        "8080808080808080808080808080808080808080808080808080808080808080",
        "letter advice cage absurd amount doctor acoustic avoid letter advice cage absurd amount doctor acoustic avoid letter advice cage absurd amount doctor acoustic bless",
        "c0c519bd0e91a2ed54357d9d1ebef6f5af218a153624cf4f2da911a0ed8f7a09e2ef61af0aca007096df430022f7a2b6fb91661a9589097069720d015e4e982f",
    ),
    (
        "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
        "zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo vote",
        "dd48c104698c30cfe2b6142103248622fb7bb0ff692eebb00089b32d22484e1613912f0a5b694407be899ffd31ed3992c456cdf60f5d4564b8ba3f05a69890ad",
    ),
    (
        "9e885d952ad362caeb4efe34a8e91bd2",
        "ozone drill grab fiber curtain grace pudding thank cruise elder eight picnic",
        "274ddc525802f7c828d8ef7ddbcdc5304e87ac3535913611fbbfa986d0c9e5476c91689f9c8a54fd55bd38606aa6a8595ad213d4c9c9f9aca3fb217069a41028",
    ),
    (
        "6610b25967cdcca9d59875f5cb50b0ea75433311869e930b",
        "gravity machine north sort system female filter attitude volume fold club stay feature office ecology stable narrow fog",
        "628c3827a8823298ee685db84f55caa34b5cc195a778e52d45f59bcf75aba68e4d7590e101dc414bc1bbd5737666fbbef35d1f1903953b66624f910feef245ac",
    ),
    (
        "68a79eaca2324873eacc50cb9c6eca8cc68ea5d936f98787c60c7ebc74e6ce7c",
        "hamster diagram private dutch cause delay private meat slide toddler razor book happy fancy gospel tennis maple dilemma loan word shrug inflict delay length",
        "64c87cde7e12ecf6704ab95bb1408bef047c22db4cc7491c4271d170a1b213d20b385bc1588d9c7b38f1b39d415665b8a9030c9ec653d75e65f847d8fc1fc440",
    ),
    (
        "c0ba5a8e914111210f2bd131f3d5e08d",
        "scheme spot photo card baby mountain device kick cradle pact join borrow",
        "ea725895aaae8d4c1cf682c1bfd2d358d52ed9f0f0591131b559e2724bb234fca05aa9c02c57407e04ee9dc3b454aa63fbff483a8b11de949624b9f1831a9612",
    ),
    (
        "6d9be1ee6ebd27a258115aad99b7317b9c8d28b6d76431c3",
        "horn tenant knee talent sponsor spell gate clip pulse soap slush warm silver nephew swap uncle crack brave",
        "fd579828af3da1d32544ce4db5c73d53fc8acc4ddb1e3b251a31179cdb71e853c56d2fcb11aed39898ce6c34b10b5382772db8796e52837b54468aeb312cfc3d",
    ),
    (
        "9f6a2878b2520799a44ef18bc7df394e7061a224d2c33cd015b157d746869863",
        "panda eyebrow bullet gorilla call smoke muffin taste mesh discover soft ostrich alcohol speed nation flash devote level hobby quick inner drive ghost inside",
        "72be8e052fc4919d2adf28d5306b5474b0069df35b02303de8c1729c9538dbb6fc2d731d5f832193cd9fb6aeecbc469594a70e3dd50811b5067f3b88b28c3e8d",
    ),
    (
        "23db8160a31d3e0dca3688ed941adbf3",
        "cat swing flag economy stadium alone churn speed unique patch report train",
        "deb5f45449e615feff5640f2e49f933ff51895de3b4381832b3139941c57b59205a42480c52175b6efcffaa58a2503887c1e8b363a707256bdd2b587b46541f5",
    ),
    (
        "8197a4a47f0425faeaa69deebc05ca29c0a5b5cc76ceacc0",
        "light rule cinnamon wrap drastic word pride squirrel upgrade then income fatal apart sustain crack supply proud access",
        "4cbdff1ca2db800fd61cae72a57475fdc6bab03e441fd63f96dabd1f183ef5b782925f00105f318309a7e9c3ea6967c7801e46c8a58082674c860a37b93eda02",
    ),
    (
        "066dca1a2bb7e8a1db2832148ce9933eea0f3ac9548d793112d9a95c9407efad",
        "all hour make first leader extend hole alien behind guard gospel lava path output census museum junior mass reopen famous sing advance salt reform",
        "26e975ec644423f4a4c4f4215ef09b4bd7ef924e85d1d17c4cf3f136c2863cf6df0a475045652c57eb5fb41513ca2a2d67722b77e954b4b3fc11f7590449191d",
    ),
    (
        "f30f8c1da665478f49b001d94c5fc452",
        "vessel ladder alter error federal sibling chat ability sun glass valve picture",
        "2aaa9242daafcee6aa9d7269f17d4efe271e1b9a529178d7dc139cd18747090bf9d60295d0ce74309a78852a9caadf0af48aae1c6253839624076224374bc63f",
    ),
    (
        "c10ec20dc3cd9f652c7fac2f1230f7a3c828389a14392f05",
        "scissors invite lock maple supreme raw rapid void congress muscle digital elegant little brisk hair mango congress clump",
        "7b4a10be9d98e6cba265566db7f136718e1398c71cb581e1b2f464cac1ceedf4f3e274dc270003c670ad8d02c4558b2f8e39edea2775c9e232c7cb798b069e88",
    ),
    (
        "f585c11aec520db57dd353c69554b21a89b20fb0650966fa0a9d6f74fd989d8f",
        "void come effort suffer camp survey warrior heavy shoot primary clutch crush open amazing screen patrol group space point ten exist slush involve unfold",
        "01f5bced59dec48e362f2c45b5de68b9fd6c92c6634f44d6d40aab69056506f0e35524a518034ddc1192e1dacd32c1ed3eaa3c3b131c88ed8e7e54c49a5d0998",
    ),
];

/// 15- and 21-word English vectors, which **the canonical suite does not contain** — it
/// covers 12, 18 and 24 only, and all five accepted lengths are required.
///
/// So these eight are ours, computed by a second implementation in a second language:
/// CPython's `hashlib.sha256` and `hashlib.pbkdf2_hmac`, driven by the algorithm read off
/// BIP-39. That generator was first run against all 24 canonical English vectors and the
/// seed step of all 24 bip32JP Japanese vectors and reproduced every one, which is what
/// makes it worth believing at the two lengths nobody publishes. The entropy patterns are
/// the ones the canonical set uses at its own lengths.
const ENGLISH_15_21: &[(&str, &str, &str)] = &[
    (
        "0000000000000000000000000000000000000000",
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon address",
        "fa08713f46bf5cb48728ceb70e3aae1bc53c5cb7b4e29c5610261d1cbb7be3bed4d805256fec515754d2be35974fc5da678168e9d9bb0cb70948026923b0def3",
    ),
    (
        "7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f",
        "legal winner thank year wave sausage worth useful legal winner thank year wave sausage wise",
        "f938c2f3ebd11f1c9057b713d977b5260e4282a57811ab163a9708c4ce15307983ac24c4451c7cb353b2002d0a1ee8a404fa59f0f6aa8323fa9bb61248cf4808",
    ),
    (
        "8080808080808080808080808080808080808080",
        "letter advice cage absurd amount doctor acoustic avoid letter advice cage absurd amount doctor accident",
        "bc40a19ec918698b32e3e13ed906006d9e3b9987ba7dee6fc53a824774cc5be68f89b865bbfbac21b2fb99c016e214f54f239f77dd99881c1b81de275c60be3d",
    ),
    (
        "ffffffffffffffffffffffffffffffffffffffff",
        "zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo wrist",
        "bfee6f9d2bcfa1331bd6482a24abca521e5f7e769498b9a0146672194c7356e4e409be22bc379c8b64fee2aa24b54d3ec20d10a083eaa5d1d6b4b365941ad37c",
    ),
    (
        "00000000000000000000000000000000000000000000000000000000",
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon admit",
        "e7dadc189d2e8d07ac278d9ec98a1d2d327e4a6b7df494c00cbf2cbf2d3543dac7000fc72d4ada8d9997dc8db388ff22c6d79f604a7455f2df5534a28eee04c6",
    ),
    (
        "7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f",
        "legal winner thank year wave sausage worth useful legal winner thank year wave sausage worth useful legal winner thank year viable",
        "99c0597b2bef5ca4859e21075fee0fc931747a30469b6f564d95f74913c357aceb55221b4f4fe6965e871340b45754b1ae59e53da1797b69b30c5fa40ec105b8",
    ),
    (
        "80808080808080808080808080808080808080808080808080808080",
        "letter advice cage absurd amount doctor acoustic avoid letter advice cage absurd amount doctor acoustic avoid letter advice cage absurd apart",
        "708f0487a927474944ed882e5f05954656bd82bebcf4119b1233e90ee8b27b16d48a77be2c2aceecc32b07a94a5e9a04d94856a2b9fd7c2362ac4153420ef2e6",
    ),
    (
        "ffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
        "zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo veteran",
        "4aa0af4ca02ef1d9fa675cd02aa06d318425564e7fadd3d51b6165cc56d77398f28d8522073cd036c2a4a24a83e919211c84500d96cb120084e613ff5fcd96c1",
    ),
];

/// The bip32JP Japanese vectors: `(entropy_hex, mnemonic, seed_hex)`, passphrase
/// [`JP_PASSPHRASE`]. **Mandatory, not optional** (`05-testing-and-release.md` §2): `㍍`
/// (U+334D) is a *compatibility* character, so it decomposes under NFKD and is left
/// untouched by NFD. These are the only vectors in the suite that tell the two apart — an
/// implementation reaching for NFD passes everything else in this file.
///
/// From <https://github.com/bip32JP/bip32JP.github.io/blob/master/test_JP_BIP39.json>. The
/// entropy column is carried for the record and never fed to our wordlist, which is
/// English: only the seed step is under test here, and it is wordlist-independent. The
/// mnemonics keep U+3000 IDEOGRAPHIC SPACE as their separator exactly as that file has
/// them; NFKD maps it to U+0020, which is the whole reason our own words may be joined with
/// a plain space.
const JAPANESE: &[(&str, &str, &str)] = &[
    (
        "00000000000000000000000000000000",
        "あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あおぞら",
        "a262d6fb6122ecf45be09c50492b31f92e9beb7d9a845987a02cefda57a15f9c467a17872029a9e92299b5cbdf306e3a0ee620245cbd508959b6cb7ca637bd55",
    ),
    (
        "7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f",
        "そつう　れきだい　ほんやく　わかす　りくつ　ばいか　ろせん　やちん　そつう　れきだい　ほんやく　わかめ",
        "aee025cbe6ca256862f889e48110a6a382365142f7d16f2b9545285b3af64e542143a577e9c144e101a6bdca18f8d97ec3366ebf5b088b1c1af9bc31346e60d9",
    ),
    (
        "80808080808080808080808080808080",
        "そとづら　あまど　おおう　あこがれる　いくぶん　けいけん　あたえる　いよく　そとづら　あまど　おおう　あかちゃん",
        "e51736736ebdf77eda23fa17e31475fa1d9509c78f1deb6b4aacfbd760a7e2ad769c714352c95143b5c1241985bcb407df36d64e75dd5a2b78ca5d2ba82a3544",
    ),
    (
        "ffffffffffffffffffffffffffffffff",
        "われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　ろんぶん",
        "4cd2ef49b479af5e1efbbd1e0bdc117f6a29b1010211df4f78e2ed40082865793e57949236c43b9fe591ec70e5bb4298b8b71dc4b267bb96ed4ed282c8f7761c",
    ),
    (
        "000000000000000000000000000000000000000000000000",
        "あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あらいぐま",
        "d99e8f1ce2d4288d30b9c815ae981edd923c01aa4ffdc5dee1ab5fe0d4a3e13966023324d119105aff266dac32e5cd11431eeca23bbd7202ff423f30d6776d69",
    ),
    (
        "7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f",
        "そつう　れきだい　ほんやく　わかす　りくつ　ばいか　ろせん　やちん　そつう　れきだい　ほんやく　わかす　りくつ　ばいか　ろせん　やちん　そつう　れいぎ",
        "eaaf171efa5de4838c758a93d6c86d2677d4ccda4a064a7136344e975f91fe61340ec8a615464b461d67baaf12b62ab5e742f944c7bd4ab6c341fbafba435716",
    ),
    (
        "808080808080808080808080808080808080808080808080",
        "そとづら　あまど　おおう　あこがれる　いくぶん　けいけん　あたえる　いよく　そとづら　あまど　おおう　あこがれる　いくぶん　けいけん　あたえる　いよく　そとづら　いきなり",
        "aec0f8d3167a10683374c222e6e632f2940c0826587ea0a73ac5d0493b6a632590179a6538287641a9fc9df8e6f24e01bf1be548e1f74fd7407ccd72ecebe425",
    ),
    (
        "ffffffffffffffffffffffffffffffffffffffffffffffff",
        "われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　りんご",
        "f0f738128a65b8d1854d68de50ed97ac1831fc3a978c569e415bbcb431a6a671d4377e3b56abd518daa861676c4da75a19ccb41e00c37d086941e471a4374b95",
    ),
    (
        "0000000000000000000000000000000000000000000000000000000000000000",
        "あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　あいこくしん　いってい",
        "23f500eec4a563bf90cfda87b3e590b211b959985c555d17e88f46f7183590cd5793458b094a4dccc8f05807ec7bd2d19ce269e20568936a751f6f1ec7c14ddd",
    ),
    (
        "7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f",
        "そつう　れきだい　ほんやく　わかす　りくつ　ばいか　ろせん　やちん　そつう　れきだい　ほんやく　わかす　りくつ　ばいか　ろせん　やちん　そつう　れきだい　ほんやく　わかす　りくつ　ばいか　ろせん　まんきつ",
        "cd354a40aa2e241e8f306b3b752781b70dfd1c69190e510bc1297a9c5738e833bcdc179e81707d57263fb7564466f73d30bf979725ff783fb3eb4baa86560b05",
    ),
    (
        "8080808080808080808080808080808080808080808080808080808080808080",
        "そとづら　あまど　おおう　あこがれる　いくぶん　けいけん　あたえる　いよく　そとづら　あまど　おおう　あこがれる　いくぶん　けいけん　あたえる　いよく　そとづら　あまど　おおう　あこがれる　いくぶん　けいけん　あたえる　うめる",
        "6b7cd1b2cdfeeef8615077cadd6a0625f417f287652991c80206dbd82db17bf317d5c50a80bd9edd836b39daa1b6973359944c46d3fcc0129198dc7dc5cd0e68",
    ),
    (
        "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
        "われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　われる　らいう",
        "a44ba7054ac2f9226929d56505a51e13acdaa8a9097923ca07ea465c4c7e294c038f3f4e7e4b373726ba0057191aced6e48ac8d183f3a11569c426f0de414623",
    ),
    (
        "77c2b00716cec7213839159e404db50d",
        "せまい　うちがわ　あずき　かろう　めずらしい　だんち　ますく　おさめる　ていぼう　あたる　すあな　えしゃく",
        "344cef9efc37d0cb36d89def03d09144dd51167923487eec42c487f7428908546fa31a3c26b7391a2b3afe7db81b9f8c5007336b58e269ea0bd10749a87e0193",
    ),
    (
        "b63a9c59a6e641f288ebc103017f1da9f8290b3da6bdef7b",
        "ぬすむ　ふっかつ　うどん　こうりつ　しつじ　りょうり　おたがい　せもたれ　あつめる　いちりゅう　はんしゃ　ごますり　そんけい　たいちょう　らしんばん　ぶんせき　やすみ　ほいく",
        "b14e7d35904cb8569af0d6a016cee7066335a21c1c67891b01b83033cadb3e8a034a726e3909139ecd8b2eb9e9b05245684558f329b38480e262c1d6bc20ecc4",
    ),
    (
        "3e141609b97933b66a060dcddc71fad1d91677db872031e85f4c015c5e7e8982",
        "くのう　てぬぐい　そんかい　すろっと　ちきゅう　ほあん　とさか　はくしゅ　ひびく　みえる　そざい　てんすう　たんぴん　くしょう　すいようび　みけん　きさらぎ　げざん　ふくざつ　あつかう　はやい　くろう　おやゆび　こすう",
        "32e78dce2aff5db25aa7a4a32b493b5d10b4089923f3320c8b287a77e512455443298351beb3f7eb2390c4662a2e566eec5217e1a37467af43b46668d515e41b",
    ),
    (
        "0460ef47585604c5660618db2e6a7e7f",
        "あみもの　いきおい　ふいうち　にげる　ざんしょ　じかん　ついか　はたん　ほあん　すんぽう　てちがい　わかめ",
        "0acf902cd391e30f3f5cb0605d72a4c849342f62bd6a360298c7013d714d7e58ddf9c7fdf141d0949f17a2c9c37ced1d8cb2edabab97c4199b142c829850154b",
    ),
    (
        "72f60ebac5dd8add8d2a25a797102c3ce21bc029c200076f",
        "すろっと　にくしみ　なやむ　たとえる　へいこう　すくう　きない　けってい　とくべつ　ねっしん　いたみ　せんせい　おくりがな　まかい　とくい　けあな　いきおい　そそぐ",
        "9869e220bec09b6f0c0011f46e1f9032b269f096344028f5006a6e69ea5b0b8afabbb6944a23e11ebd021f182dd056d96e4e3657df241ca40babda532d364f73",
    ),
    (
        "2c85efc7f24ee4573d2b81a6ec66cee209b2dcbd09d8eddc51e0215b0b68e416",
        "かほご　きうい　ゆたか　みすえる　もらう　がっこう　よそう　ずっと　ときどき　したうけ　にんか　はっこう　つみき　すうじつ　よけい　くげん　もくてき　まわり　せめる　げざい　にげる　にんたい　たんそく　ほそく",
        "713b7e70c9fbc18c831bfd1f03302422822c3727a93a5efb9659bec6ad8d6f2c1b5c8ed8b0b77775feaf606e9d1cc0a84ac416a85514ad59f5541ff5e0382481",
    ),
    (
        "eaebabb2383351fd31d703840b32e9e2",
        "めいえん　さのう　めだつ　すてる　きぬごし　ろんぱ　はんこ　まける　たいおう　さかいし　ねんいり　はぶらし",
        "06e1d5289a97bcc95cb4a6360719131a786aba057d8efd603a547bd254261c2a97fcd3e8a4e766d5416437e956b388336d36c7ad2dba4ee6796f0249b10ee961",
    ),
    (
        "7ac45cfe7722ee6c7ba84fbc2d5bd61b45cb2fe5eb65aa78",
        "せんぱい　おしえる　ぐんかん　もらう　きあい　きぼう　やおや　いせえび　のいず　じゅしん　よゆう　きみつ　さといも　ちんもく　ちわわ　しんせいじ　とめる　はちみつ",
        "1fef28785d08cbf41d7a20a3a6891043395779ed74503a5652760ee8c24dfe60972105ee71d5168071a35ab7b5bd2f8831f75488078a90f0926c8e9171b2bc4a",
    ),
    (
        "4fa1a8bc3e6d80ee1316050e862c1812031493212b7ec3f3bb1b08f168cabeef",
        "こころ　いどう　きあつ　そうがんきょう　へいあん　せつりつ　ごうせい　はいち　いびき　きこく　あんい　おちつく　きこえる　けんとう　たいこ　すすめる　はっけん　ていど　はんおん　いんさつ　うなぎ　しねま　れいぼう　みつかる",
        "43de99b502e152d4c198542624511db3007c8f8f126a30818e856b2d8a20400d29e7a7e3fdd21f909e23be5e3c8d9aee3a739b0b65041ff0b8637276703f65c2",
    ),
    (
        "18ab19a9f54a9274f03e5209a2ac8a91",
        "うりきれ　さいせい　じゆう　むろん　とどける　ぐうたら　はいれつ　ひけつ　いずれ　うちあわせ　おさめる　おたく",
        "3d711f075ee44d8b535bb4561ad76d7d5350ea0b1f5d2eac054e869ff7963cdce9581097a477d697a2a9433a0c6884bea10a2193647677977c9820dd0921cbde",
    ),
    (
        "18a2e1d81b8ecfb2a333adcb0c17a5b9eb76cc5d05db91a4",
        "うりきれ　うねる　せっさたくま　きもち　めんきょ　へいたく　たまご　ぜっく　びじゅつかん　さんそ　むせる　せいじ　ねくたい　しはらい　せおう　ねんど　たんまつ　がいけん",
        "753ec9e333e616e9471482b4b70a18d413241f1e335c65cd7996f32b66cf95546612c51dcf12ead6f805f9ee3d965846b894ae99b24204954be80810d292fcdd",
    ),
    (
        "15da872c95a13dd738fbf50e427583ad61f18fd99f628c417a61cf8343c90419",
        "うちゅう　ふそく　ひしょ　がちょう　うけもつ　めいそう　みかん　そざい　いばる　うけとる　さんま　さこつ　おうさま　ぱんつ　しひょう　めした　たはつ　いちぶ　つうじょう　てさぎょう　きつね　みすえる　いりぐち　かめれおん",
        "346b7321d8c04f6f37b49fdf062a2fddc8e1bf8f1d33171b65074531ec546d1d3469974beccb1a09263440fc92e1042580a557fdce314e27ee4eabb25fa5e5fe",
    ),
];

/// The passphrase every Japanese vector above carries.
const JP_PASSPHRASE: &str = "㍍ガバヴァぱばぐゞちぢ十人十色";
