# Feature: service-layer-security-refactor, Property 4: Stats service equivalence (get_color_identities)
"""
Property test verifying that `get_color_identities()` returns the same list of
{name, imgs} dicts as the original N+1 implementation (get_ci), including the
colorless fallback when a color identity has no components with images.

**Validates: Requirements 3.3, 3.6, 5.1, 5.2, 5.3**
"""
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import ColorIdentity, Color, ColorComponent
from app.services.stats_service import get_color_identities


# --- Strategies ---

# Generate short, unique color names (used as primary keys)
color_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), min_codepoint=65, max_codepoint=122),
    min_size=1,
    max_size=10,
)

# Generate optional image URLs (some colors have no image)
img_strategy = st.one_of(st.none(), st.text(min_size=1, max_size=50))


@st.composite
def color_identity_data(draw):
    """Generate a consistent set of ColorIdentity, Color, and ColorComponent records.

    Ensures foreign key constraints are satisfied:
    - Each ColorComponent references an existing ColorIdentity and Color
    - Color names are unique (primary keys)
    - ColorIdentity names are unique (primary keys)
    - ColorComponent (color_identity, color) pairs are unique (composite PK)
    """
    # Generate a set of unique color names (0-8 colors)
    num_colors = draw(st.integers(min_value=0, max_value=8))
    color_names = draw(
        st.lists(
            color_name_strategy,
            min_size=num_colors,
            max_size=num_colors,
            unique=True,
        )
    )

    # Generate colors with optional images
    colors = []
    for name in color_names:
        img = draw(img_strategy)
        colors.append({'name': name, 'abbreviation': name[:3] or 'X', 'img': img})

    # Generate a set of unique identity names (1-6 identities)
    num_identities = draw(st.integers(min_value=1, max_value=6))
    identity_names = draw(
        st.lists(
            color_name_strategy,
            min_size=num_identities,
            max_size=num_identities,
            unique=True,
        )
    )

    # Generate identities
    identities = []
    for name in identity_names:
        identities.append({'name': name, 'amount': draw(st.integers(min_value=0, max_value=100))})

    # Generate color components (subset of identity x color pairs)
    possible_pairs = [(ci, c) for ci in identity_names for c in color_names]
    if possible_pairs:
        num_components = draw(st.integers(min_value=0, max_value=len(possible_pairs)))
        chosen_pairs = draw(
            st.lists(
                st.sampled_from(possible_pairs),
                min_size=num_components,
                max_size=num_components,
                unique=True,
            )
        )
    else:
        chosen_pairs = []

    components = [{'color_identity': ci, 'color': c} for ci, c in chosen_pairs]

    # Optionally include a 'Colorless' color entry for fallback behavior
    include_colorless = draw(st.booleans())
    if include_colorless and 'Colorless' not in color_names:
        colorless_img = draw(st.one_of(st.none(), st.text(min_size=1, max_size=50)))
        colors.append({'name': 'Colorless', 'abbreviation': 'C', 'img': colorless_img})

    return {
        'colors': colors,
        'identities': identities,
        'components': components,
    }


def reference_get_ci():
    """Original N+1 implementation of get_ci() used as reference.

    This reproduces the exact behavior of the original code for equivalence testing.
    """
    ci_list = []
    colorless = Color.query.filter_by(name='Colorless').first()
    colorless_img = colorless.img if colorless and colorless.img else None

    identities = ColorIdentity.query.all()
    for identity in identities:
        components = ColorComponent.query.filter_by(color_identity=identity.name).all()
        imgs = []
        for comp in components:
            color = Color.query.filter_by(name=comp.color).first()
            if color and color.img:
                imgs.append(color.img)
        if not imgs and colorless_img:
            imgs = [colorless_img]
        ci_list.append({'name': identity.name, 'imgs': imgs})
    return ci_list


@given(data=color_identity_data())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_get_color_identities_equivalence(app, db_session, data):
    """Property 4: get_color_identities() SHALL return the same list of {name, imgs}
    dicts as the original N+1 implementation for any set of ColorIdentity,
    ColorComponent, and Color records, including the colorless fallback.
    """
    with app.app_context():
        # Clear existing data (order matters for FK constraints)
        db_session.query(ColorComponent).delete()
        db_session.query(Color).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        # Insert generated data
        for color_data in data['colors']:
            color = Color(
                name=color_data['name'],
                abbreviation=color_data['abbreviation'],
                img=color_data['img'],
            )
            db_session.add(color)

        for identity_data in data['identities']:
            identity = ColorIdentity(
                name=identity_data['name'],
                amount=identity_data['amount'],
            )
            db_session.add(identity)

        db_session.flush()

        for comp_data in data['components']:
            component = ColorComponent(
                color_identity=comp_data['color_identity'],
                color=comp_data['color'],
            )
            db_session.add(component)

        db_session.flush()

        # Run both implementations
        new_result = get_color_identities()
        reference_result = reference_get_ci()

        # Both should have the same number of entries
        assert len(new_result) == len(reference_result), (
            f"Length mismatch: new={len(new_result)}, reference={len(reference_result)}"
        )

        # Convert to comparable form: sort by name, and sort imgs within each entry
        def normalize(result_list):
            return sorted(
                [{'name': r['name'], 'imgs': sorted(r['imgs'])} for r in result_list],
                key=lambda x: x['name'],
            )

        new_normalized = normalize(new_result)
        ref_normalized = normalize(reference_result)

        assert new_normalized == ref_normalized, (
            f"Results differ:\n  new: {new_normalized}\n  ref: {ref_normalized}"
        )
