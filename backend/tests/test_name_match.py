"""Matching a distributor's spelling to the masters without an alias each time.
The cases are spellings from the real MAPPING_MASTER history."""
from app.services.name_match import Matcher, words


def customers(*rows):
    m = Matcher("customer")
    for i, n in rows:
        m.add_master(i, n)
    return m


C = customers((16539402, "ASHMA MEDICO"), (15657702, "AASHMA MEDIC"),
              (19, "BAIBHAV & BINAYAK PHARMACEUTICALS"), (74, "KAMANA DRUG DISTRIBUTORS"),
              (75, "KAMANA MEDICINE DISTRIBUTOR"), (501, "MEDICHEM PHARMA"),
              (502, "MEDICHEM PHARMA JKP"), (18779614, "AISHWARYA MEDICINE DISTRIBUTORS"))


def test_company_words_and_plurals_do_not_count():
    assert C.find("Ashma Medico Pvt ltd") == (16539402, "cleaned")
    assert C.find("AISHWARYA MEDICINE DISTRIBUTOR") == (18779614, "cleaned")
    assert words("M/S Ashma Medico P. Ltd.", "customer") == ("ASHMA", "MEDICO")


def test_a_name_cut_short_or_with_a_town_code():
    assert C.find("Baibhav Binayak Pharmaceutic") == (19, "shortened")
    assert C.find("KAMANA MEDICINE DIST.PVT.LTD KTM") == (75, "shortened")
    assert C.find("KAMANA DRUG DISTRIBUTORS BTL") == (74, "shortened")


def test_two_masters_that_begin_alike_are_asked_about():
    # MEDICHEM PHARMA and MEDICHEM PHARMA JKP: a third spelling is not guessed
    assert C.find("MEDICHEM PHARMA JANAKPUR") == (None, None)
    assert C.find("MEDICHEM PHARMA JNK") == (None, None)
    assert [s["id"] for s in C.suggest("MEDICHEM PHARMA JANAKPUR")][:2] in ([501, 502], [502, 501])


def test_a_near_name_is_not_its_neighbour():
    # ASHMA MEDICO and AASHMA MEDIC are two customers
    assert C.find("AASHMA MEDIC") == (15657702, "exact")
    assert C.find("Ashma Medico") == (16539402, "exact")


def test_history_and_choices_come_before_likeness():
    m = customers((1, "SAYAPATRI MEDICINE CONCERN"), (2, "JANAPREMI MEDICAL"))
    m.add_history("JANAPREMI MED HALL BHARATPUR", 2, 40, own=True)
    m.add_history("JANAPREMI MED HALL BHARATPUR", 1, 1, own=False)   # a slip in the old data
    assert m.find("Janapremi Med Hall Bharatpur") == (2, "history")
    m.add_chosen("JMH BTP", 2)
    assert m.find("J.M.H. Btp") == (2, "chosen")


def products(*rows):
    m = Matcher("product")
    for i, n in rows:
        m.add_master(i, n)
    return m


P = products((50, "UDILIV 150MG"), (51, "UDILIV 300MG"), (49, "UDILIV 600MG"),
             (60, "APNICAF 3 ML"), (61, "APNICAF SOLUTION"), (70, "STEMETIL 5MG TAB"),
             (71, "STEMETIL MD TABLETS 1X10S"), (80, "BRUFEN 600 MG 15S"), (81, "BRUFEN 400 MG 15S"),
             (90, "DUSPATALIN 135 MG"), (91, "DUSPATALIN RETARD 200 MG"), (100, "THYRONORM 37.5 MG 100S"),
             (101, "THYRONORM 75 MG 120S"), (110, "CREMAFFIN M/F 225ML"), (111, "CREMAFFIN PLAIN 225ML"),
             (120, "DIGENE GEL ORANGE 200ML"), (121, "DIGENE GEL MINT 200ML"), (130, "ROVAMYCIN 3 MIU"),
             (131, "ROVAMYCIN FORTE"), (140, "KIDPRED SYRUP 60ML"), (150, "CREMALAX TAB 10S"),
             (151, "CREMALAX TAB 15 S"))


def test_products_tablet_words_units_and_pack_sizes_do_not_count():
    assert P.find("UDILIV 300MG TAB") == (51, "cleaned")
    assert P.find("STEMETIL 5MG TAB") == (70, "exact")
    assert P.find("STEMETIL MD") == (71, "cleaned")                       # 1X10S is a pack
    assert P.find("BRUFEN 600 (15 S) 15S") == (80, "cleaned")
    assert P.find("DUSPATALIN 135 MG 5X10S") == (90, "cleaned")
    assert P.find("THYRONORM 37.5 MG 120S 120S") == (100, "cleaned")      # 37.5, not 37 and 5
    assert P.find("CREMAFFIN M/F 225ML 225ML") == (110, "cleaned")
    assert P.find("KIDPRED SYP") == (140, "shortened")                    # SYP = SYRUP
    assert P.find("DIGENE GEL (O) PET 200 ML") == (120, "shortened")      # O = ORANGE


def test_products_keep_their_strength_and_their_form():
    assert P.find("UDILIV 450MG TAB") == (None, None)                     # no such strength
    assert P.find("BRUFEN 800") == (None, None)
    assert P.find("APNICAF INJ 3ML") == (None, None)                      # injection or oral? asked
    assert P.find("ROVAMYCIN FORTE TAB") == (131, "cleaned")
    assert P.find("ROVAMYCIN 3 MIU FORTE") == (None, None)                # FORTE, or 3 MIU? asked
    assert P.find("CREMALAX TAB 6 S 6S") == (None, None)                  # 10S or 15S? asked
    assert P.find("STEMETL 5MG") == (70, "similar")                       # a slip of the keys
