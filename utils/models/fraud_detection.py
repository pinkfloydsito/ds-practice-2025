import pandas as pd
import numpy as np
import joblib
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder

np.random.seed(42)

data_size = 5000
data = {
    "amount": np.random.uniform(1, 10000, data_size),  # Transaction amount
    "payment_method": np.random.choice(["Credit Card", "PayPal", "Crypto", "Bank Transfer"], data_size),
    "location": np.random.choice(["USA", "UK", "India", "North Korea", "Syria"], data_size),
    "fraudulent": np.random.choice([0, 1], data_size, p=[0.95, 0.05])  # 5% fraud cases
}

df = pd.DataFrame(data)


label_encoders = {
    "payment_method": LabelEncoder(),
    "location": LabelEncoder(),
}

for col, le in label_encoders.items():
    df[col] = le.fit_transform(df[col])


X = df.drop("fraudulent", axis=1)
y = df["fraudulent"]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)


model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)


joblib.dump(model, "fraud_model.pkl")
joblib.dump(label_encoders, "label_encoders.pkl")

print("Model trained and saved!")
