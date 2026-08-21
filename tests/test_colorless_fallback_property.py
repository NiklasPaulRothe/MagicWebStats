# Feature: raw-sql-to-orm, Property 12: Colorless Fallback
"""
Property test verifying that `resolve_color_images` returns a list containing
exactly the Colorless color's image URL when no color components with non-null
images exist for a given color identity.

**Validates: Requirements 2.5, 3.9, 4.7, 5.7**
"""

import pytest

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import Color, ColorComponent, ColorIdentity
from app.services.color_service import resolve_color_images


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate identity names that won't collide with real ones
identity_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=3,
    max_size=20,
).filter(lambda s: s != "Colorless")

# Generate a valid image URL for Colorless
colorless_img_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="/:._-"),
    min_size=5,
    max_size=80,
).filter(lambda s: len(s.strip()) > 0)

# Generate color names for components whose images will be None
color_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L",)),
    min_size=2,
    max_size=15,
).filter(lambda s: s != "Colorless")


@st.composite
def colorless_fallback_scenario(draw):
    """Generate a scenario where resolve_color_images should fall back to Colorless.

    Two cases:
    1. identity_name has NO color components at all
    2. identity_name has color components but ALL their Color entries have img=None
    """
    identity_name = draw(identity_name_strategy)
    colorless_img = draw(colorless_img_strategy)

    # Decide scenario: no components or components with null images
    has_components = draw(st.booleans())

    components_with_null_imgs = []
    if has_components:
        # Generate 1-4 color components whose Color.img is None
        num_components = draw(st.integers(min_value=1, max_value=4))
        color_names = draw(
            st.lists(
                color_name_strategy,
                min_size=num_components,
                max_size=num_components,
                unique=True,
            )
        )
        components_with_null_imgs = color_names

    return {
        "identity_name": identity_name,
        "colorless_img": colorless_img,
        "components_with_null_imgs": components_with_null_imgs,
    }


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


@given(data=colorless_fallback_scenario())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_colorless_fallback(app, db_session, data):
    """Property 12: For any deck or color identity where the color_imgs list is empty
    (no color components with non-null images), the resolve function SHALL return a
    list containing exactly the Colorless color's image URL.
    """
    with app.app_context():
        # Clean existing data
        db_session.query(ColorComponent).delete()
        db_session.query(Color).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        identity_name = data["identity_name"]
        colorless_img = data["colorless_img"]
        components_with_null_imgs = data["components_with_null_imgs"]

        # Insert the Colorless color with a valid img
        colorless_color = Color(name="Colorless", abbreviation="C", img=colorless_img)
        db_session.add(colorless_color)

        # Insert the color identity
        ci = ColorIdentity(name=identity_name, amount=0)
        db_session.add(ci)
        db_session.flush()

        # Insert color components with null images (if any)
        for color_name in components_with_null_imgs:
            # Create the color entry with img=None
            color = Color(name=color_name, abbreviation=color_name[0].upper(), img=None)
            db_session.add(color)
            db_session.flush()

            # Create the color component linking identity to this color
            comp = ColorComponent(color_identity=identity_name, color=color_name)
            db_session.add(comp)

        db_session.flush()

        # Call the function under test
        result = resolve_color_images(identity_name)

        # Verify: result should be exactly [colorless_img]
        assert result == [colorless_img], (
            f"Expected [{colorless_img!r}] but got {result!r}. "
            f"Identity: {identity_name!r}, "
            f"Components with null imgs: {components_with_null_imgs}"
        )
