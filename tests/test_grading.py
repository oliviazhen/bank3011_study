from engine.grading import blank_matches, definition_correct, grade_blanks, normalise


def test_normalise_symbols_case_articles_subscripts():
    assert normalise("The Credit Spread.") == "credit spread"
    assert normalise("MMR₁") == "mmr1"
    assert normalise("D × L") == "d * l"
    assert normalise("Φ") == "phi"


def test_synonyms_case_and_spacing():
    acc = ["creditworthiness", "credit quality"]
    assert blank_matches("Creditworthiness", acc)
    assert blank_matches("credit worthiness", acc)
    assert blank_matches("credit-quality", acc)
    assert blank_matches("the credit quality", acc)


def test_small_typos_accepted_on_long_words():
    assert blank_matches("creditworthyness", ["creditworthiness"])      # 1 letter
    assert blank_matches("credtworthines", ["creditworthiness"])        # 2 letters, long word
    assert blank_matches("borower", ["borrower"])
    assert not blank_matches("bxrrxwxr", ["borrower"])


def test_plural_and_singular():
    assert blank_matches("borrowers", ["borrower"])
    assert blank_matches("covenant", ["covenants"])


def test_opposites_never_accepted():
    assert not blank_matches("increases", ["decreases"])
    assert not blank_matches("decrease", ["increase"])
    assert not blank_matches("unsecured", ["secured"])
    assert not blank_matches("lender", ["borrower"])
    assert not blank_matches("higher", ["lower"])


def test_short_terms_and_symbols_must_be_exact():
    assert blank_matches("MMR1", ["MMR₁"])
    assert blank_matches("mmr₁", ["MMR₁"])
    assert not blank_matches("MMR2", ["MMR₁"])
    assert not blank_matches("LGD", ["PD"])
    assert not blank_matches("EAD", ["LGD"])
    assert blank_matches("phi", ["Φ"])


def test_numbers():
    assert blank_matches("1.81", ["1.81"])
    assert blank_matches(" 1.810 ", ["1.81"])
    assert not blank_matches("1.18", ["1.81"])
    assert not blank_matches("2.99", ["1.81"])
    assert blank_matches("8%", ["8%", "0.08"])


def test_empty_answer_is_wrong():
    assert not blank_matches("", ["borrower"])
    assert not blank_matches("   ", ["borrower"])


def test_multi_blank_question():
    q = {"blanks": [["borrower"], ["bank", "lender"]]}
    assert grade_blanks(q, ["Borrower", "the lender"]) == (True, [True, True])
    assert grade_blanks(q, ["borrower", "borrower"]) == (False, [True, False])
    assert grade_blanks(q, ["borrower"]) == (False, [True, False])          # missing blank


def test_definition_threshold():
    assert definition_correct(2, 3) and not definition_correct(1, 3)     # 2 of 3
    assert definition_correct(3, 4) and not definition_correct(2, 4)     # 3 of 4
    assert definition_correct(3, 3)
    assert not definition_correct(0, 0)
