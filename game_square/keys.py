"""
Standalone key constants — SDL2 keycodes used by the game.

These match the integer values pygame-ce returns from pygame.K_*.
Defining them here lets the server run without pygame installed
(only tornado is needed for the web server).
"""

K_w      = 119
K_s      = 115
K_a      = 97
K_d      = 100
K_e      = 101
K_f      = 102
K_n      = 110
K_m      = 109
K_UP     = 1073741906
K_DOWN   = 1073741905
K_LEFT   = 1073741904
K_RIGHT  = 1073741903
