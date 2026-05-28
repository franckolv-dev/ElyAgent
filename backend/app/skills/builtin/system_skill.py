# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/app/skills/builtin/system_skill.py
# @brief      System Skill module
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
# @license    Elastic License 2.0
#            https://www.elastic.co/licensing/elastic-license
# @version    1.1.0
# @link       https://github.com/franckolv-dev/PhysicalAgent
#
# RÉSUMÉ DES CONDITIONS :
#   - AUTORISÉ : Usage personnel et professionnel interne (gratuit).
#   - AUTORISÉ : Modification et redistribution avec attribution.
#   - INTERDIT : Revente comme SaaS / service managé à des tiers.
#   - INTERDIT : Suppression des notices de copyright ou de licence.
# =============================================================================
from app.skills.base import Skill, Domain
from app.skills.registry import get_skill_registry
from app.agent.tools.ssh_tool import ssh_execute
from app.agent.tools.file_tool import analyze_file
from app.agent.tools.system_tool import system_info

get_skill_registry().register(Skill(
    name="system",
    display_name="Système & SSH",
    description="Exécuter des commandes SSH sur des serveurs distants, analyser des fichiers, obtenir des infos système",
    icon="🖥️",
    scopes=["ssh"],
    domains=[Domain.INFRA],
    tools=[ssh_execute, analyze_file, system_info],
))
