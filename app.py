import json
import os
import random
from flask import Flask, request, jsonify

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

from state import load_game, save_game, delete_game
from prompts import PROMPTS, GAGES, CATEGORIES

TOKEN = os.environ.get("BOT_TOKEN", "")

app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

def to_label(cat):
    return CATEGORIES.get(cat, "FUN")

def new_game_state():
    return {
        "players": [], "scores": {}, "passes": {},
        "eliminated": [], "used": {},
        "index": 0, "turn": 0, "active": False,
        "category": "fun", "last_type": None, "last_prompt": "",
        "history": [],
        "settings": {"tournament": False, "timer": True}
    }

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
        "category": category, "prompt": prompt
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

def keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Vérité", callback_data="truth"),
         InlineKeyboardButton("⚡ Action", callback_data="dare")],
        [InlineKeyboardButton("⏭️ Passer", callback_data="pass"),
         InlineKeyboardButton("➡️ Next", callback_data="next")]
    ])

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    g = load_game(update.effective_chat.id) or new_game_state()
    if len(g["players"]) < 2:
        return await update.message.reply_text(
            "Ajoute des joueurs avec /ajouter Nom\n"
            "Puis /lancer pour démarrer.\n\n"
            "/ajouter Nom - ajouter\n/supprimer Nom - retirer\n"
            "/joueurs - lister\n/fun, /amis, /soft, /hot - ambiance\n"
            "/scores - classement\n/tournoi - mode tournoi\n"
            "/regles - règles\n/fin - terminer"
        )
    g["active"] = True
    g["turn"] = 0
    p = get_player(g)
    save_game(update.effective_chat.id, g)
    await update.message.reply_text(
        f"🎲 *Partie lancée !*\nAmbiance : {to_label(g['category'])}\n"
        f"Joueurs : {', '.join(g['players'])}\n\nAu tour de *{p}*",
        parse_mode="Markdown", reply_markup=keyboard()
    )

async def cmd_ajouter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    g = load_game(update.effective_chat.id) or new_game_state()
    nom = " ".join(ctx.args).strip()
    if not nom:
        return await update.message.reply_text("Usage : /ajouter Nom")
    if nom in g["players"]:
        return await update.message.reply_text(f"{nom} déjà présent.")
    g["players"].append(nom)
    g["scores"][nom] = 0
    g["passes"][nom] = 0
    save_game(update.effective_chat.id, g)
    await update.message.reply_text(f"✅ {nom} ajouté\nJoueurs : {', '.join(g['players'])}")

async def cmd_supprimer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    g = load_game(update.effective_chat.id)
    if not g:
        return await update.message.reply_text("Aucune partie.")
    nom = " ".join(ctx.args).strip()
    if not nom or nom not in g["players"]:
        return await update.message.reply_text(f"Joueur '{nom}' introuvable.")
    g["players"].remove(nom); g["scores"].pop(nom, None)
    g["passes"].pop(nom, None)
    if nom in g["eliminated"]: g["eliminated"].remove(nom)
    save_game(update.effective_chat.id, g)
    await update.message.reply_text(f"🗑️ {nom} supprimé.")

async def cmd_joueurs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    g = load_game(update.effective_chat.id)
    if not g or not g["players"]:
        return await update.message.reply_text("Aucun joueur.")
    lines = [f"👥 *Joueurs*\nAmbiance : {to_label(g['category'])}"]
    for p in g["players"]:
        pts = g["scores"].get(p, 0)
        elim = " ❌" if p in g["eliminated"] else ""
        pss = g["passes"].get(p, 0)
        note = f" ({pss}/3)" if g["settings"]["tournament"] and pss > 0 and p not in g["eliminated"] else ""
        lines.append(f"• {p}{elim} — {pts} pts{note}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_scores(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    g = load_game(update.effective_chat.id)
    if not g: return await update.message.reply_text("Aucune partie.")
    await update.message.reply_text(format_scores(g), parse_mode="Markdown")

async def cmd_lancer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)

async def cmd_ambiance(update, ctx, cat):
    g = load_game(update.effective_chat.id) or new_game_state()
    g["category"] = cat; save_game(update.effective_chat.id, g)
    await update.message.reply_text(f"Ambiance → *{to_label(cat)}*", parse_mode="Markdown")

async def cmd_fun(update, ctx): await cmd_ambiance(update, ctx, "fun")
async def cmd_amis(update, ctx): await cmd_ambiance(update, ctx, "amis")
async def cmd_soft(update, ctx): await cmd_ambiance(update, ctx, "soft")
async def cmd_hot(update, ctx): await cmd_ambiance(update, ctx, "hot")

async def cmd_tournoi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    g = load_game(update.effective_chat.id) or new_game_state()
    g["settings"]["tournament"] = not g["settings"]["tournament"]
    if not g["settings"]["tournament"]:
        g["eliminated"] = []; g["passes"] = {p: 0 for p in g["players"]}
    save_game(update.effective_chat.id, g)
    s = "✅ Activé" if g["settings"]["tournament"] else "❌ Désactivé"
    await update.message.reply_text(f"🏆 Mode Tournoi {s}", parse_mode="Markdown")

async def cmd_regles(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Règles*\n1. /ajouter Nom (min 2)\n"
        "2. Choisir ambiance: /fun, /amis, /soft, /hot\n"
        "3. /lancer → cliquer Vérité ou Action\n"
        "4. Répondre puis Next\n5. /passer = 0 pt\n"
        "6. 3 passes en tournoi = élimination\n"
        "7. Timer → gage\n8. /tournoi pour activer",
        parse_mode="Markdown"
    )

async def cmd_fin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    delete_game(update.effective_chat.id)
    await update.message.reply_text("Partie terminée.")

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    cid = update.effective_chat.id; g = load_game(cid)
    if not g or not g["active"]:
        return await query.edit_message_text("Aucune partie active.")
    p = get_player(g)
    if query.data in ("truth", "dare"):
        actif = active_players(g)
        if g["settings"]["tournament"] and len(actif) < 2:
            await query.edit_message_text("🎉 *Fin !*\n"+format_scores(g), parse_mode="Markdown")
            return delete_game(cid)
        if g["settings"]["tournament"] and p in g["eliminated"]:
            next_player(g, True); p = get_player(g)
        prompt = get_unused(g, g["category"], query.data, p)
        g["last_type"] = query.data; g["last_prompt"] = prompt
        g["turn"] += 1; g["scores"][p] = g["scores"].get(p, 0) + 1
        tl = "VÉRITÉ" if query.data == "truth" else "ACTION"
        add_history(g, p, tl, to_label(g["category"]), prompt)
        save_game(cid, g)
        await query.edit_message_text(
            f"🎯 *{tl} pour {p}*\n\n*{prompt}*\n\nRéponds puis Next 👇",
            parse_mode="Markdown", reply_markup=keyboard())
    elif query.data == "pass":
        if g["settings"]["tournament"]:
            g["passes"][p] = g["passes"].get(p, 0) + 1
            if g["passes"][p] >= 3:
                g["eliminated"].append(p)
                if len(active_players(g)) < 2:
                    save_game(cid, g)
                    await query.edit_message_text(f"❌ {p} éliminé!\n🎉 *Fin!*\n"+format_scores(g), parse_mode="Markdown")
                    return delete_game(cid)
                next_player(g, True); p2 = get_player(g); save_game(cid, g)
                return await query.edit_message_text(f"❌ {p} éliminé! Au tour de *{p2}*", parse_mode="Markdown", reply_markup=keyboard())
        add_history(g, p, "PASSÉ", to_label(g["category"]), "A passé"); save_game(cid, g)
        note = f" ({g['passes'].get(p,0)}/3)" if g["settings"]["tournament"] else ""
        await query.edit_message_text(f"⏭️ {p} a passé{note}", reply_markup=keyboard())
    elif query.data == "next":
        g["turn"] += 1; next_player(g, False); p2 = get_player(g)
        if g["settings"]["tournament"] and p2 in g["eliminated"]:
            if len(active_players(g)) < 2:
                save_game(cid, g); await query.edit_message_text("🎉 *Fin !*\n"+format_scores(g), parse_mode="Markdown")
                return delete_game(cid)
            next_player(g, False); p2 = get_player(g)
        save_game(cid, g)
        await query.edit_message_text(f"✅ Au tour de *{p2}* 👇", parse_mode="Markdown", reply_markup=keyboard())

application.add_handler(CommandHandler("start", cmd_start))
application.add_handler(CommandHandler("lancer", cmd_lancer))
application.add_handler(CommandHandler("ajouter", cmd_ajouter))
application.add_handler(CommandHandler("supprimer", cmd_supprimer))
application.add_handler(CommandHandler("joueurs", cmd_joueurs))
application.add_handler(CommandHandler("scores", cmd_scores))
application.add_handler(CommandHandler("fun", cmd_fun))
application.add_handler(CommandHandler("amis", cmd_amis))
application.add_handler(CommandHandler("soft", cmd_soft))
application.add_handler(CommandHandler("hot", cmd_hot))
application.add_handler(CommandHandler("tournoi", cmd_tournoi))
application.add_handler(CommandHandler("regles", cmd_regles))
application.add_handler(CommandHandler("fin", cmd_fin))
application.add_handler(CallbackQueryHandler(handle_callback))

@app.route("/", methods=["GET"])
def index():
    return "Bot Action ou Vérité — OK"

@app.route("/api/set_webhook", methods=["GET"])
def set_webhook():
    import asyncio
    url = f"{request.host_url}api/webhook"
    asyncio.run(application.bot.set_webhook(url=url))
    return f"Webhook set to {url}"

@app.route("/api/webhook", methods=["POST"])
def webhook():
    try:
        body = request.get_json(force=True)
        update = Update.de_json(body, application.bot)
        import asyncio
        asyncio.run(application.process_update(update))
        return "OK"
    except Exception as e:
        return jsonify({"error": str(e)}), 200
