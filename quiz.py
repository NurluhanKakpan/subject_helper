import fitz  # PyMuPDF
import os
import re
import random
import time
import json
import google.generativeai as genai
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackContext,
    ConversationHandler,
    filters
)

# Configuration
GOOGLE_API_KEY = "AIzaSyAYS1h8HHeu1XI4VwhaPwh5wV9V2V3XCLw"
TELEGRAM_TOKEN = "7588260134:AAHGfL1EtWABE11Kb0j1umhddMP2bBZgZ34"
PDF_PATH = "history.pdf"

# Initialize Gemini
genai.configure(api_key=GOOGLE_API_KEY)

generation_config = {
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 8192,
    "response_mime_type": "application/json",
}

model = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    generation_config=generation_config,
)

# Conversation states
QUESTION, ANSWER = range(2)

def extract_qa_from_pdf():
    """Извлекает вопросы и ответы из PDF, учитывая перенос строк и определяя ответы по жирному шрифту."""
    try:
        doc = fitz.open(PDF_PATH)
        qa_pairs = []
        current_question = []
        current_answer = []
        collecting_answer = False  # Флаг, чтобы понимать, идет ли сбор ответа

        for page in doc:
            blocks = page.get_text("dict")["blocks"]  # Получаем текстовые блоки

            for block in blocks:
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            text = span["text"].strip()
                            is_bold = "bold" in span["font"].lower()  # Проверяем, жирный ли шрифт

                            if is_bold:
                                # Если начался жирный текст, это начало ответа
                                if current_question:
                                    collecting_answer = True
                                    current_answer.append(text)
                            else:
                                if collecting_answer:
                                    # Если уже собираем ответ, но встретился обычный текст, значит, ответ завершен
                                    full_question = " ".join(current_question).strip()
                                    full_answer = " ".join(current_answer).strip()
                                    qa_pairs.append((full_question, full_answer))
                                    
                                    # Очистка и начало нового вопроса
                                    current_question = [text]
                                    current_answer = []
                                    collecting_answer = False
                                else:
                                    # Если еще не начался ответ, продолжаем собирать вопрос
                                    current_question.append(text)

        # Добавляем последний Q/A, если остался незаписанный ответ
        if current_question and current_answer:
            full_question = " ".join(current_question).strip()
            full_answer = " ".join(current_answer).strip()
            qa_pairs.append((full_question, full_answer))

        return qa_pairs

    except Exception as e:
        print(f"Ошибка при обработке PDF: {e}")
        return []

def generate_distractors(question, correct_answer):
    """Generate 3 distractors using Gemini with array response handling."""
    prompt = f"""
    Сгенерируй ТОЛЬКО 3 НЕВЕРНЫХ ответа на вопрос.
    Ответ должен быть строго в ОДНОМ JSON-объекте:
    {{
        "question": "{question}",
        "correct_answer": "{correct_answer.strip().replace('\n', ' ')}",
        "incorrect_answers": ["Ответ1", "Ответ2", "Ответ3"]
    }}
    Не используй markdown! Только чистый JSON! Только 3 ответа! Не более! Не менее!  
    """
    
    try:
        response = model.generate_content(prompt)
        print("Raw Gemini Response:", response.text)
        
        # Clean response and parse first JSON object
        json_str = response.text.strip()
        json_str = json_str.replace("```json", "").replace("```", "").strip()
        
        # Handle array responses
        if json_str.startswith('['):
            data = json.loads(json_str)[0]  # Take first element of array
        else:
            data = json.loads(json_str)
        
        # Clean newlines from answers
        incorrect_answers = [ans.replace('\n', ' ').strip() 
                           for ans in data.get("incorrect_answers", [])]
        
        return incorrect_answers[:3]  # Return maximum 3 answers
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return ["Вариант 1", "Вариант 2", "Вариант 3"]

async def start(update: Update, context: CallbackContext):
    await update.message.reply_text("Привет! Для начала теста отправь /quiz")
    return ConversationHandler.END

async def start_quiz(update: Update, context: CallbackContext):
    # Load all questions and shuffle them
    qa_pairs = extract_qa_from_pdf()
    if not qa_pairs:
        await update.message.reply_text("Ошибка загрузки вопросов.")
        return ConversationHandler.END
    
    random.shuffle(qa_pairs)
    context.user_data.update({
        "qa_pairs": qa_pairs,
        "score": 0,
        "current": 0,
        "total": len(qa_pairs)
    })
    
    return await ask_random_question(update, context)

async def ask_random_question(update: Update, context: CallbackContext):
    user_data = context.user_data
    index = user_data["current"]
    
    if index >= user_data["total"]:
        return await finish_quiz(update, context)
    
    # Get random question from remaining
    question, correct_answer = user_data["qa_pairs"][index]
    
    # Generate options for this question
    distractors = generate_distractors(question, correct_answer)
    options = [correct_answer] + distractors
    random.shuffle(options)
    correct_index = options.index(correct_answer)
    
    # Store current question info
    user_data["current_question"] = {
        "options": options,
        "correct_index": correct_index
    }
    
    # Create keyboard
    keyboard = [[opt] for opt in options]
    
    await update.message.reply_text(
        f"Вопрос {index+1}/{user_data['total']}:\n{question}",
        reply_markup=ReplyKeyboardMarkup(
            keyboard, 
            one_time_keyboard=True,
            resize_keyboard=True
        )
    )
    
    return ANSWER

async def handle_answer(update: Update, context: CallbackContext):
    user_data = context.user_data
    user_answer = update.message.text.replace('\n', ' ').strip()
    current_question = user_data.get("current_question")


    
    correct_answer = current_question["options"][current_question["correct_index"]]
    correct_answer = correct_answer.replace('\n', ' ').strip()



    if not current_question:
        await update.message.reply_text("Ошибка: данные вопроса не найдены.")
        return ConversationHandler.END
    
    correct_answer = current_question["options"][current_question["correct_index"]]

    correct_answer = correct_answer.replace('\n', ' ').strip()
    
    if user_answer == correct_answer:
        user_data["score"] += 1
        feedback = "✅ Правильно!"
    else:
        feedback = f"❌ Неверно! Правильный ответ: {correct_answer}"
    
    await update.message.reply_text(feedback)
    
    # Move to next question
    user_data["current"] += 1
    return await ask_random_question(update, context)

async def finish_quiz(update: Update, context: CallbackContext):
    user_data = context.user_data
    score = user_data["score"]
    total = user_data["total"]
    await update.message.reply_text(
        f"Тест завершен!\nПравильных ответов: {score}/{total} ({score/total:.0%})"
    )
    return ConversationHandler.END

def main():
    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .get_updates_http_version("1.1")
        .build()
    )
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start),
                      CommandHandler("quiz", start_quiz)],
        states={
            ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer)]
        },
        fallbacks=[CommandHandler("cancel", finish_quiz)],
        conversation_timeout=300
    )
    
    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == "__main__":
    main()