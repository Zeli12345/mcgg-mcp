"""Static game knowledge used by the layout and gear planners.

Two kinds of data live here:

- Facts read from the running client's config tables (hero names and costs, item names
  and quality). These were read through the bridge's /cfg endpoint on Magic Chess: Go Go
  1.3.24.344.1 and are the authoritative roster for that build. Costs are `quality`.
- Judgements that the client does not expose: each hero's combat role and range, each
  item's damage family, and synergy membership. These come from published guides and
  general auto-battler knowledge. They are NOT verified against this build. Correct a
  row here when the screen or a live match shows it is wrong; the planners read only
  this table.
"""
from __future__ import annotations

# name -> (role, range, damage)
#   role:   tank | bruiser | assassin | marksman | mage | support
#   range:  melee | ranged
#   damage: phys | magic | hybrid
HERO_INFO = {
    'Miya': ('marksman', 'ranged', 'phys'),
    'Balmond': ('bruiser', 'melee', 'phys'),
    'Saber': ('assassin', 'melee', 'phys'),
    'Alice': ('mage', 'ranged', 'magic'),
    'Nana': ('support', 'ranged', 'magic'),
    'Tigreal': ('tank', 'melee', 'phys'),
    'Karina': ('assassin', 'melee', 'magic'),
    'Franco': ('tank', 'melee', 'phys'),
    'Clint': ('marksman', 'ranged', 'phys'),
    'Eudora': ('mage', 'ranged', 'magic'),
    'Zilong': ('bruiser', 'melee', 'phys'),
    'Fanny': ('assassin', 'melee', 'phys'),
    'Layla': ('marksman', 'ranged', 'phys'),
    'Minotaur': ('tank', 'melee', 'phys'),
    'Lolita': ('tank', 'melee', 'magic'),
    'Gord': ('mage', 'ranged', 'magic'),
    'Natalia': ('assassin', 'ranged', 'phys'),
    'Alpha': ('bruiser', 'melee', 'phys'),
    'Yi Sun-shin': ('bruiser', 'melee', 'phys'),
    'Moskov': ('bruiser', 'ranged', 'phys'),
    'Hilda': ('tank', 'melee', 'phys'),
    'Vexana': ('mage', 'ranged', 'magic'),
    'Karrie': ('marksman', 'ranged', 'phys'),
    'Gatotkaca': ('tank', 'melee', 'phys'),
    'Harley': ('mage', 'ranged', 'magic'),
    'Irithel': ('marksman', 'ranged', 'phys'),
    'Odette': ('mage', 'ranged', 'magic'),
    'Lancelot': ('assassin', 'melee', 'phys'),
    'Hylos': ('tank', 'melee', 'phys'),
    'Angela': ('support', 'ranged', 'magic'),
    'Gusion': ('assassin', 'melee', 'phys'),
    'Martis': ('bruiser', 'melee', 'phys'),
    'Uranus': ('tank', 'melee', 'magic'),
    'Aldous': ('bruiser', 'melee', 'phys'),
    'Vale': ('mage', 'ranged', 'magic'),
    'Lunox': ('mage', 'ranged', 'magic'),
    'Belerick': ('tank', 'melee', 'phys'),
    'Thamuz': ('tank', 'melee', 'magic'),
    'Kadita': ('mage', 'ranged', 'magic'),
    'Badang': ('tank', 'melee', 'phys'),
    'Granger': ('marksman', 'ranged', 'phys'),
    'X.Borg': ('assassin', 'melee', 'phys'),
    'Dyrroth': ('bruiser', 'melee', 'phys'),
    'Baxia': ('tank', 'melee', 'phys'),
    'Wanwan': ('marksman', 'ranged', 'phys'),
    'Atlas': ('tank', 'melee', 'phys'),
    'Luo Yi': ('mage', 'ranged', 'magic'),
    'Mathilda': ('support', 'ranged', 'magic'),
    'Paquito': ('bruiser', 'melee', 'phys'),
    'Phoveus': ('tank', 'melee', 'magic'),
    'Edith': ('tank', 'melee', 'phys'),
    'Yin': ('bruiser', 'melee', 'phys'),
    'Melissa': ('marksman', 'ranged', 'phys'),
    'Novaria': ('mage', 'ranged', 'magic'),
    'Cici': ('bruiser', 'melee', 'phys'),
    'Zhuxin': ('mage', 'ranged', 'magic'),
    'Suyou': ('tank', 'melee', 'phys'),
    'Sora': ('mage', 'ranged', 'magic'),
}

# name -> cost (gold), from the client config table (`quality`)
HERO_COST = {
    'Miya': 2, 'Balmond': 2, 'Saber': 3, 'Alice': 5, 'Nana': 5, 'Tigreal': 3, 'Karina': 3,
    'Franco': 3, 'Clint': 3, 'Eudora': 1, 'Zilong': 4, 'Fanny': 5, 'Layla': 5, 'Minotaur': 1,
    'Lolita': 4, 'Gord': 4, 'Natalia': 2, 'Alpha': 7, 'Yi Sun-shin': 1, 'Moskov': 5,
    'Hilda': 3, 'Vexana': 4, 'Karrie': 4, 'Gatotkaca': 5, 'Harley': 2, 'Irithel': 4,
    'Odette': 5, 'Lancelot': 5, 'Hylos': 2, 'Angela': 2, 'Gusion': 4, 'Martis': 2,
    'Uranus': 1, 'Aldous': 3, 'Vale': 1, 'Lunox': 4, 'Belerick': 2, 'Thamuz': 5,
    'Kadita': 3, 'Badang': 5, 'Granger': 2, 'X.Borg': 5, 'Dyrroth': 1, 'Baxia': 5,
    'Wanwan': 3, 'Atlas': 4, 'Luo Yi': 2, 'Mathilda': 3, 'Paquito': 3, 'Phoveus': 1,
    'Edith': 3, 'Yin': 4, 'Melissa': 5, 'Novaria': 5, 'Cici': 1, 'Zhuxin': 2, 'Suyou': 4,
    'Sora': 4,
}

# Item families. Crystals are not equipment slots and are excluded by the gear planner.
#   phys / magic / hybrid: the damage family the item boosts
#   defense: durability (HP, defence, reflect, taunt)
#   basic: skill-upgrade and utility items with no damage family
#   special: copy, reward or set items
ITEM_FAMILY = {
    "Demon Hunter Sword": 'phys', "Golden Staff": 'phys', "War Axe": 'phys',
    "Sea Halberd": 'phys', "Blade of Despair": 'phys', "Berserker's Fury": 'phys',
    "Haas' Claws": 'phys', "Great Dragon Spear": 'phys', "Hunting Revolver": 'phys',
    "Justice Sword": 'phys', "Guren Chakram": 'phys', "Nether Claw": 'phys',
    "Blazing Hammer": 'phys',
    "Ice Queen Wand": 'magic', "Glowing Wand": 'magic', "Holy Crystal": 'magic',
    "Divine Glaive": 'magic', "Sun Staff": 'magic', "Knowledge Crystal": 'magic',
    "Essence Core": 'magic', "Fluffy's Rage": 'magic',
    "Winter Crown": 'hybrid', "Spellblade Talisman": 'hybrid', "Purple Buff": 'hybrid',
    "Feline Blade": 'hybrid', "Lightstick": 'hybrid',
    "Guardian Helmet": 'defense', "Antique Cuirass": 'defense', "Blade Armor": 'defense',
    "Dominance Ice": 'defense', "Thunder Belt": 'defense', "Oracle": 'defense',
    "Ancient Wrath": 'defense', "Sunset Shield": 'defense',
    "Aegis": 'basic', "Inspire": 'basic', "Purify": 'basic', "Retribution": 'basic',
    "Revitalize": 'basic', "Flicker": 'basic',
    "Mirror Device": 'special', "Claude's Theft Device": 'special',
    "Exorcist's Seal": 'special',
}

# value of an item family to a hero role (before the damage-type scaling in gear.py)
FAMILY_ROLE_VALUE = {
    'phys': {'marksman': 3.0, 'assassin': 2.6, 'bruiser': 2.2, 'tank': 1.0,
             'mage': 0.5, 'support': 0.5},
    'magic': {'mage': 3.0, 'support': 2.0, 'tank': 1.2, 'assassin': 0.8,
              'bruiser': 0.6, 'marksman': 0.4},
    'hybrid': {'marksman': 2.0, 'assassin': 2.0, 'bruiser': 2.0, 'mage': 2.0,
               'support': 1.5, 'tank': 1.5},
    'defense': {'tank': 3.0, 'bruiser': 2.0, 'support': 1.0, 'mage': 0.4,
                'marksman': 0.2, 'assassin': 0.2},
    'basic': {'marksman': 1.0, 'assassin': 1.0, 'bruiser': 1.0, 'mage': 1.0,
              'support': 1.0, 'tank': 1.0},
    'special': {'marksman': 1.2, 'assassin': 1.2, 'bruiser': 1.2, 'mage': 1.2,
                'support': 1.2, 'tank': 1.2},
}

# Item-name patterns that are never placed on a hero's equipment slots
CRYSTAL_SUFFIX = 'Magic Crystal'

# Synergy membership for heroes on the roster (from published guides; unverified here)
SYNERGIES = {
    'Astro Power': ['Hilda', 'Irithel', 'Karina', 'Martis', 'Minotaur', 'Odette'],
    'Bruiser': ['Aldous', 'Badang', 'Belerick', 'Dyrroth', 'Paquito', 'Yin'],
    'Dauntless': ['Alice', 'Balmond', 'Franco', 'Hilda', 'Lolita', 'Uranus'],
    'Defender': ['Atlas', 'Baxia', 'Edith', 'Hylos', 'Minotaur', 'Tigreal'],
    'Dragon Altar': ['Baxia', 'Luo Yi', 'Suyou', 'Wanwan', 'Yi Sun-shin', 'Yin'],
    'Dragoncaller': ['Badang', 'Balmond', 'Clint', 'Eudora', 'Gusion', 'Zilong'],
    'Echomancer': ['Harley', 'Natalia', 'Sora', 'Thamuz', 'Tigreal', 'Vale'],
    'Enchanted Tales': ['Atlas', 'Belerick', 'Mathilda', 'Vexana'],
    'Kishin': ['Angela', 'Dyrroth', 'Franco', 'Karrie', 'Lancelot', 'Lunox'],
    'Mage': ['Gord', 'Kadita', 'Odette', 'Vale', 'Vexana', 'Zhuxin'],
    'Marksman': ['Granger', 'Irithel', 'Karrie', 'Melissa', 'Miya', 'Wanwan'],
    'Mistbender': ['Aldous', 'Nana', 'Uranus'],
    'Phasewarper': ['Clint', 'Harley', 'Lancelot'],
    'Scavenger': ['Angela', 'Phoveus', 'Sora'],
    'Shadeweaver': ['Hylos', 'Kadita', 'Melissa'],
    'SPECTRE': ['Alice', 'Alpha', 'Gord', 'Granger', 'Paquito', 'Phoveus', 'Saber'],
    'Starbelle': ['Cici', 'Edith', 'Fanny', 'Lolita', 'Miya', 'Zhuxin'],
    'Stargazer': ['Eudora', 'Lunox', 'Luo Yi', 'Mathilda', 'Nana'],
    'Swiftblade': ['Fanny', 'Gusion', 'Karina', 'Natalia', 'Saber', 'Yi Sun-shin'],
    'Weapon Master': ['Cici', 'Martis', 'Suyou', 'Thamuz', 'Zilong'],
}

# Synergy breakpoints: units needed -> bonus, in units of one average hero's value
SYNERGY_BREAKPOINTS = ((2, 0.6), (4, 1.5), (6, 2.8))

# Sign of each hero's star level on value. Three-star heroes dominate the board.
STAR_MULTIPLIER = {1: 1.0, 2: 2.6, 3: 6.0}

# Base value by cost tier (1..5, and 7 for Alpha)
COST_VALUE = {1: 1.0, 2: 1.6, 3: 2.4, 4: 3.5, 5: 5.0, 7: 6.0}

# Share of a hero's power that counts toward the team: carries and bruisers deal the damage
ROLE_WEIGHT = {'marksman': 1.0, 'mage': 1.0, 'assassin': 0.95, 'bruiser': 0.9,
               'support': 0.7, 'tank': 0.75}


def hero_info(name):
    """(role, range, damage) for a known hero, else a neutral bruiser so unknown names still plan."""
    return HERO_INFO.get(name, ('bruiser', 'melee', 'phys'))


def item_family(name):
    """Family of an equipment item, or None for crystals and names not in the table."""
    if not name or name.endswith(CRYSTAL_SUFFIX):
        return None
    if name.startswith(('Inspire', 'Purify', 'Retribution', 'Revitalize', 'Aegis')):
        return 'basic'  # upgraded skill-item variants such as "Inspire — Burning Will"
    return ITEM_FAMILY.get(name)
