import random
import os
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler

from prompts import PROMPTS, GAGES, CATEGORIES

TOKEN = os.environ.get("BOT_TOKEN", "8657133994:AAHmcW_d4YX1F692F1_Z7slXSq5sBbbIwSU")

games = {}

def get_game(chat_id):
    if chat_id not in games:
        games[chat_id] = {
            "players": [], "scores": {}, "passes": {},
            "eliminated": [], "used": {},
            "index": 0, "turn": 0, "active": False,
            "category": "fun", "last_type": None, "last_prompt": "",
            "history": [],
            "settings": {"tournament": False, "timer": True}
        }
    return games[chat_id]

def to_label(cat):
    return CATEGORIES.get(cat, "FUN")

def active_players(g):
    return [p for p in g["players"] if p not in g["eliminated"]]

def get_player(g):
    if not g["players"]:
        return ""
    return g["players"][g["index"] % len(g["players"])]

def next_player(g, random_=False):
    if not g["players"]:
        return
    if random_:
        g["index"] = random.randint(0, len(g["players"]) - 1)
    else:
        g["index"] = (g["index"] + 1) % len(g["players"])
    if g["settings"]["tournament"] and active_players(g):
        if get_player(g) in g["eliminated"]:
            next_player(g, False)

def get_unused(g, cat, type_, player):
    pool = PROMPTS[cat][type_]
    key = f"{cat}_{type_}"
    used = g["used"].setdefault(player, {}).get(key, [])
    avail = [i for i in range(len(pool)) if i not in used]
    if not avail:
        g["used"][player][key] = []
        return random.choice(pool)
    idx = random.choice(avail)
    g["used"].setdefault(player, {}).setdefault(key, []).append(idx)
    return pool[idx]

def add_history(g, player, type_, category, prompt):
    g["history"].insert(0, {
        "player": player, "type": type_,
        "category": category, "prompt": prompt,
        "time": datetime.now().isoformat()
    })
    if len(g["history"]) > 50:
        g["history"].pop()

def format_scores(g):
    entries = sorted(
        [(n, g["scores"].get(n, 0)) for n in g["players"]],
        key=lambda x: x[1], reverse=True
    )
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (n, s) in enumerate(entries):
        elim = " ❌" if n in g["eliminated"] else ""
        medal = medals[i] if i < 3 else f"#{i+1}"
        lines.append(f"{medal} {n}{elim}: {s} pts")
    return "🏆 *Scores*\n" + "\n".join(lines) if lines else "Aucun score."

def get_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Vérité", callback_data="truth"),
         InlineKeyboardButton("⚡ Action", callback_data="dare")],
        [InlineKeyboardButton("⏭️ Passer", callback_data="pass"),
         InlineKeyboardButton("➡️ Next", callback_data="next")]
    ])

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    g = get_game(update.effective_chat.id)
    if len(g["players"]) < 2:
        return await update.message.reply_text(
            "Ajoute des joueurs avec /ajouter Nom\n"
            "Puis /lancer pour démarrer.\n\n"
            "Commandes :\n"
            "/ajouter Nom - ajouter un joueur\n"
            "/supprimer Nom - retirer un joueur\n"
            "/joueurs - lister les joueurs\n"
            "/fun, /amis, /soft, /hot - choisir l'ambiance\n"
            "/scores - classement\n"
            "/tournoi - activer/désactiver le mode tournoi\n"
            "/regles - voir les règles\n"
            "/fin - terminer la partie"
        )
    g["active"] = True
    g["turn"] = 0
    p = get_player(g)
    await update.message.reply_text(
        f"🎲 *Partie lancée !*\n"
        f"Ambiance : {to_label(g['category'])}\n"
        f"Joueurs : {', '.join(g['players'])}\n\n"
        f"Au tour de *{p}*\n"
        f"Choisis Vérité ou Action :",
        parse_mode="Markdown", reply_markup=get_keyboard()
    )

async def cmd_ajouter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    g = get_game(update.effective_chat.id)
    nom = " ".join(ctx.args).strip()
    if not nom:
        return await update.message.reply_text("Usage : /ajouter Nom")
    if nom in g["players"]:
        return await update.message.reply_text(f"{nom} est déjà dans la partie.")
    g["players"].append(nom)
    g["scores"][nom] = 0
    g["passes"][nom] = 0
    await update.message.reply_text(
        f"✅ {nom} ajouté\n"
        f"Joueurs ({len(g['players'])}) : {', '.join(g['players'])}"
    )

async def cmd_supprimer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    g = get_game(update.effective_chat.id)
    nom = " ".join(ctx.args).strip()
    if not nom or nom not in g["players"]:
        return await update.message.reply_text(f"Joueur '{nom}' introuvable.")
    g["players"].remove(nom)
    g["scores"].pop(nom, None)
    g["passes"].pop(nom, None)
    if nom in g["eliminated"]:
        g["eliminated"].remove(nom)
    await update.message.reply_text(f"🗑️ {nom} supprimé.\nJoueurs : {', '.join(g['players'])}")

async def cmd_joueurs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    g = get_game(update.effective_chat.id)
    if not g["players"]:
        return await update.message.reply_text("Aucun joueur. Ajoute avec /ajouter Nom")
    lines = []
    for p in g["players"]:
        pts = g["scores"].get(p, 0)
        elim = " ❌" if p in g["eliminated"] else ""
        pss = g["passes"].get(p, 0)
        info = f"  ({pss}/3 passes)" if g["settings"]["tournament"] and pss > 0 and not p in g["eliminated"] else ""
        lines.append(f"• {p}{elim} — {pts} pts{info}")
    msg = f"👥 *Joueurs ({len(g['players'])})*\nAmbiance : {to_label(g['category'])}\n" + "\n".join(lines)
    if g["settings"]["tournament"]:
        msg += f"\n🏆 Mode Tournoi actif"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_scores(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    g = get_game(update.effective_chat.id)
    if not g["players"]:
        return await update.message.reply_text("Aucun joueur.")
    await update.message.reply_text(format_scores(g), parse_mode="Markdown")

async def cmd_lancer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    return await cmd_start(update, ctx)

async def cmd_ambiance(update: Update, ctx: ContextTypes.DEFAULT_TYPE, cat: str):
    g = get_game(update.effective_chat.id)
    g["category"] = cat
    await update.message.reply_text(f"Ambiance changée → *{to_label(cat)}*", parse_mode="Markdown")

async def cmd_fun(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_ambiance(update, ctx, "fun")
async def cmd_amis(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_ambiance(update, ctx, "amis")
async def cmd_soft(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_ambiance(update, ctx, "soft")
async def cmd_hot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_ambiance(update, ctx, "hot")

async def cmd_tournoi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    g = get_game(update.effective_chat.id)
    g["settings"]["tournament"] = not g["settings"]["tournament"]
    if not g["settings"]["tournament"]:
        g["eliminated"] = []
        g["passes"] = {p: 0 for p in g["players"]}
    status = "✅ Activé (3 passes = élimination)" if g["settings"]["tournament"] else "❌ Désactivé"
    await update.message.reply_text(f"🏆 Mode Tournoi {status}", parse_mode="Markdown")

async def cmd_regles(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 *Règles Action ou Vérité*\n\n"
        "1. Ajoute des joueurs avec /ajouter Nom (min 2)\n"
        "2. Choisis une ambiance : /fun, /amis, /soft, /hot\n"
        "3. Lance la partie avec /lancer\n"
        "4. À chaque tour : Vérité ou Action\n"
        "5. Le joueur répond, puis tape /next (ou clique Next)\n"
        "6. /passer pour passer (0 pt, compte en tournoi)\n"
        "7. Après 3 passes en tournoi → élimination ❌\n"
        "8. Le timer (30s) donne un gage automatique\n\n"
        "🏆 Le dernier en tournoi gagne la partie !"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_fin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in games:
        del games[chat_id]
    await update.message.reply_text("Partie terminée. À bientôt !")

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    g = get_game(chat_id)
    if not g or not g["active"]:
        return await query.edit_message_text("Aucune partie active. Envoie /lancer")

    p = get_player(g)
    action = query.data

    if action in ("truth", "dare"):
        actif = active_players(g)
        if g["settings"]["tournament"] and len(actif) < 2:
            return await query.edit_message_text(
                "🎉 *Partie terminée !*\n" + format_scores(g),
                parse_mode="Markdown"
            )
        if g["settings"]["tournament"] and p in g["eliminated"]:
            next_player(g, True)
            p = get_player(g)

        prompt = get_unused(g, g["category"], action, p)
        g["last_type"] = action
        g["last_prompt"] = prompt
        g["turn"] += 1
        g["scores"][p] = g["scores"].get(p, 0) + 1

        type_label = "VÉRITÉ" if action == "truth" else "ACTION"
        add_history(g, p, type_label, to_label(g["category"]), prompt)

        msg = (
            f"🎯 *{type_label} pour {p}*\n"
            f"Ambiance : {to_label(g['category'])}\n\n"
            f"*{prompt}*\n\n"
            f"Réponds puis clique Next 👇"
        )
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=get_keyboard())

    elif action == "pass":
        if g["settings"]["tournament"]:
            g["passes"][p] = g["passes"].get(p, 0) + 1
            if g["passes"][p] >= 3:
                g["eliminated"].append(p)
                add_history(g, p, "ÉLIMINÉ", to_label(g["category"]), f"{p} éliminé (3 passes)")
                remaining = active_players(g)
                if len(remaining) < 2:
                    await query.edit_message_text(
                        f"❌ {p} éliminé !\n\n🎉 *Partie terminée !*\n" + format_scores(g),
                        parse_mode="Markdown"
                    )
                    return
                next_player(g, False)
                p2 = get_player(g)
                await query.edit_message_text(
                    f"❌ {p} est éliminé ! (3 passes)\n\n"
                    f"Au tour de *{p2}* 👇",
                    parse_mode="Markdown", reply_markup=get_keyboard()
                )
                return
        add_history(g, p, "PASSÉ", to_label(g["category"]), f"A passé son tour")
        pts_note = f" ({g['passes'][p]}/3)" if g["settings"]["tournament"] else ""
        await query.edit_message_text(
            f"⏭️ {p} a passé{pts_note}",
            reply_markup=get_keyboard()
        )

    elif action == "next":
        g["turn"] += 1
        next_player(g, False)
        p2 = get_player(g)
        if g["settings"]["tournament"] and p2 in g["eliminated"]:
            actif = active_players(g)
            if len(actif) < 2:
                await query.edit_message_text(
                    "🎉 *Partie terminée !*\n" + format_scores(g),
                    parse_mode="Markdown"
                )
                return
            next_player(g, False)
            p2 = get_player(g)
        await query.edit_message_text(
            f"✅ +1 point\n➡️ Au tour de *{p2}*\nChoisis Vérité ou Action :",
            parse_mode="Markdown", reply_markup=get_keyboard()
        )

async def post_init(app):
    print(f"Bot démarré : @{app.bot.username}")

def main():
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("lancer", cmd_lancer))
    app.add_handler(CommandHandler("ajouter", cmd_ajouter))
    app.add_handler(CommandHandler("supprimer", cmd_supprimer))
    app.add_handler(CommandHandler("joueurs", cmd_joueurs))
    app.add_handler(CommandHandler("scores", cmd_scores))
    app.add_handler(CommandHandler("fun", cmd_fun))
    app.add_handler(CommandHandler("amis", cmd_amis))
    app.add_handler(CommandHandler("soft", cmd_soft))
    app.add_handler(CommandHandler("hot", cmd_hot))
    app.add_handler(CommandHandler("tournoi", cmd_tournoi))
    app.add_handler(CommandHandler("regles", cmd_regles))
    app.add_handler(CommandHandler("fin", cmd_fin))
    app.add_handler(CallbackQueryHandler(handle_callback))
    print("Bot prêt. Démarrage du polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
